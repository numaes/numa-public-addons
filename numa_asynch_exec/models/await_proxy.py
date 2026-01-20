"""
Await Proxy for Chained Asynchronous Execution

Implements a fluent API for creating dependent asynchronous jobs.
Supports sequential and parallel execution patterns.
"""

from odoo import models, api
from ..utils import get_asynch_executor, _run_in_thread, make_json_serializable
import logging

_logger = logging.getLogger(__name__)


class AwaitProxy:
    """
    Proxy object that builds a chain of dependent asynchronous jobs.
    
    Supports:
    - Sequential execution: job_wait().method1().method2()
    - Parallel execution: job_wait().method1().job_wait().method2().method3()
    - Complex chains with multiple levels
    
    Example:
        # Sequential: method2 runs after method1 completes
        recordset.job_wait().method1().method2()
        
        # Parallel: method1 and method2 run simultaneously, method3 runs after both complete
        recordset.job_wait().method1().job_wait().method2().method3()
    """
    
    def __init__(self, recordset, parent_job_ids=None, retry=0, retry_delay=0, parent_proxy=None):
        """
        Initialize the await proxy.
        
        :param recordset: The recordset to execute methods on
        :param parent_job_ids: List of job IDs that must complete before this chain
        :param retry: Number of retries for jobs in this chain
        :param retry_delay: Delay in milliseconds for jobs in this chain
        :param parent_proxy: Reference to parent proxy (for parallel groups)
        """
        self.recordset = recordset
        self.parent_job_ids = parent_job_ids or []
        self.retry = retry
        self.retry_delay = retry_delay
        self.chain = []  # List of (method_name, args, kwargs) tuples
        self.parallel_groups = []  # List of parallel AwaitProxy instances
        self.parent_proxy = parent_proxy  # Reference to parent proxy
    
    def job_wait(self, retry=0, retry_delay=0):
        """
        Start a new parallel execution branch.
        
        When called within a chain, creates a new parallel branch.
        Subsequent method calls will be added to this parallel branch.
        When a method is called after parallel branches exist, those branches
        are finalized and their final jobs become dependencies.
        
        :param retry: Number of retries for this branch
        :param retry_delay: Delay in milliseconds for this branch
        :return: New AwaitProxy instance for parallel execution
        """
        # Find the root proxy (the one that manages parallel groups)
        root_proxy = self
        while root_proxy.parent_proxy:
            root_proxy = root_proxy.parent_proxy
        
        # Create a new proxy for parallel execution
        # It shares the same parent_job_ids as the current proxy
        new_proxy = AwaitProxy(
            self.recordset,
            parent_job_ids=self.parent_job_ids.copy(),
            retry=retry or self.retry,
            retry_delay=retry_delay or self.retry_delay,
            parent_proxy=root_proxy  # Link to root for finalization
        )
        # Store this proxy as a parallel group in the root
        root_proxy.parallel_groups.append(new_proxy)
        # Return the new proxy so subsequent calls go to it
        return new_proxy
    
    def __getattr__(self, name):
        """
        Intercept method calls and add them to the chain.
        
        Special handling: If this proxy has a parent (it's a parallel branch),
        we need to route the call to the parent after finalizing this branch.
        If this is the root proxy and has parallel groups, finalize them first.
        
        :param name: Method name
        :return: Callable that adds method to chain
        """
        def _add_to_chain(*args, **kwargs):
            # If this proxy has a parent, we're in a parallel branch
            # Route the call to the parent proxy
            if self.parent_proxy:
                # Finalize this parallel branch first
                parallel_job_ids = self._create_jobs()
                # The last job becomes a dependency for the parent
                if parallel_job_ids:
                    self.parent_proxy.parent_job_ids.append(parallel_job_ids[-1])
                # Remove this from parent's parallel groups
                if self in self.parent_proxy.parallel_groups:
                    self.parent_proxy.parallel_groups.remove(self)
                # Route call to parent
                return getattr(self.parent_proxy, name)(*args, **kwargs)
            
            # This is the root proxy
            # If we have parallel groups, finalize them first
            if self.parallel_groups:
                # Finalize all parallel groups to get their final job IDs
                parallel_final_jobs = []
                for parallel_proxy in self.parallel_groups[:]:  # Copy list to avoid modification during iteration
                    # Create jobs for this parallel branch
                    parallel_job_ids = parallel_proxy._create_jobs()
                    # The last job in each parallel branch is the final one
                    if parallel_job_ids:
                        parallel_final_jobs.append(parallel_job_ids[-1])
                
                # These final jobs become parents for the sequential chain
                if parallel_final_jobs:
                    self.parent_job_ids.extend(parallel_final_jobs)
                
                # Clear parallel groups as they're now processed
                self.parallel_groups = []
            
            # Add method to current chain
            self.chain.append((name, args, kwargs))
            # Return self to allow chaining
            return self
        return _add_to_chain
    
    def _create_jobs(self):
        """
        Create all jobs for this chain.
        
        Note: Parallel groups should be finalized before calling this method
        (they are handled in __getattr__ when a method is called after job_wait()).
        
        :return: List of created job IDs (for the final job's dependencies)
        """
        all_job_ids = []
        current_parents = self.parent_job_ids.copy()
        
        # Create jobs for sequential chain
        for i, (method_name, args, kwargs) in enumerate(self.chain):
            # Create job
            job_vals = {
                'db_name': self.recordset.env.cr.dbname,
                'model_name': self.recordset._name,
                'res_ids': self.recordset.ids,
                'method_name': method_name,
                'args': make_json_serializable(args),
                'kwargs': make_json_serializable(kwargs),
                'context': make_json_serializable(self.recordset.env.context),
                'uid': self.recordset.env.uid,
                'max_retries': self.retry,
                'retry_delay': self.retry_delay,
            }
            
            job = self.recordset.env['numa.asynch.job'].sudo().create(job_vals)
            
            # Create dependencies if needed
            if current_parents:
                for parent_id in current_parents:
                    self.recordset.env['numa.asynch.job.dependency'].sudo().create({
                        'job_id': job.id,
                        'depends_on_id': parent_id,
                    })
                # Refresh to get computed fields
                job.refresh()
                # Set state to waiting if has dependencies
                if job.has_dependencies:
                    job.write({'state': 'waiting'})
            
            # This job becomes parent for next job in chain
            current_parents = [job.id]
            all_job_ids.append(job.id)
            
            # Submit job if no dependencies (or if dependencies already done)
            job.refresh()
            if not job.has_dependencies or job.all_dependencies_done:
                def _submit_job(job_id=job.id, dbname=job.db_name, ctx=job.context):
                    get_asynch_executor().submit(_run_in_thread, job_id, dbname, ctx)
                self.recordset.env.cr.postcommit.add(_submit_job)
        
        return all_job_ids
    
    def _finalize(self):
        """
        Finalize the chain by creating all jobs.
        Called when the chain is complete (no more method calls).
        """
        # If this is a parallel branch, don't finalize here (parent will handle it)
        if self.parent_proxy:
            return self._create_jobs()
        
        # This is the root proxy - handle parallel groups first
        if self.parallel_groups:
            parallel_final_jobs = []
            for parallel_proxy in self.parallel_groups:
                parallel_job_ids = parallel_proxy._create_jobs()
                if parallel_job_ids:
                    parallel_final_jobs.append(parallel_job_ids[-1])
            if parallel_final_jobs:
                self.parent_job_ids.extend(parallel_final_jobs)
            self.parallel_groups = []
        
        return self._create_jobs()
