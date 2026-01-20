from odoo import models, api
from ..utils import get_asynch_executor, _run_in_thread, make_json_serializable
from .await_proxy import AwaitProxy

import logging
_logger = logging.getLogger(__name__)


class AsynchProxy:
    """
    A proxy object that intercepts method calls on a recordset and
    enqueues them for asynchronous execution.
    """
    def __init__(self, recordset, retry=0, retry_delay=0):
        self.recordset = recordset
        self.retry = retry
        self.retry_delay = retry_delay

    def __getattr__(self, name):
        """
        Intercepts the method call and returns a wrapper that creates an
        asynchronous job instead of executing the method immediately.
        """
        def _asynch_call(*args, **kwargs):
            # Capture all metadata needed for asynchronous execution
            dbname = self.recordset.env.cr.dbname
            model_name = self.recordset._name
            res_ids = self.recordset.ids
            job_vals = {
                'db_name': dbname,
                'model_name': model_name,
                'res_ids': self.recordset.ids,
                'method_name': name,
                'args': make_json_serializable(args),
                'kwargs': make_json_serializable(kwargs),
                'context': make_json_serializable(self.recordset.env.context),
                'uid': self.recordset.env.uid,
                'max_retries': self.retry,
                'retry_delay': self.retry_delay,
            }
            # Create the job record in sudo mode to ensure persistence
            _logger.debug(f'Creating asynchronous job: {job_vals}')
            job = self.recordset.env['numa.asynch.job'].sudo().create(job_vals)
            job_id = job.id
            _context = job.context
            
            # Register a hook to submit the job only after the current transaction is committed.
            # This ensures that the job record is visible to the background thread.
            # Instead of blocking the postcommit with the execution of the target method, schedule a task
            def _submit_job():
                get_asynch_executor().submit(_run_in_thread, job_id, dbname, _context)

            self.recordset.env.cr.postcommit.add(_submit_job)
            return True

        return _asynch_call

class Base(models.AbstractModel):
    """
    Extension of the Odoo 'base' model to provide asynchronous execution capabilities
    to all models in the system.
    """
    _inherit = 'base'

    def asynch_exec(self, retry=0, retry_delay=0):
        """
        Entry point for asynchronous execution. Returns an AsynchProxy.
        
        :param retry: Number of times to retry the job on failure.
                     Use -1 for infinite retries (system threads only - WARNING: Use with extreme caution).
                     Default: 0 (no retries)
        :param retry_delay: Delay in milliseconds before each execution/retry. Default: 0 (no delay)
        :return: AsynchProxy instance
        
        Example:
            recordset.asynch_exec(retry=3, retry_delay=500).some_heavy_method(arg1)
            
        WARNING - Infinite Retries (retry=-1):
        ----------------------------------------
        Setting retry=-1 creates an infinite retry loop. This should ONLY be used for
        system-level background threads that need to run continuously (e.g., polling,
        monitoring, periodic tasks). Using this for regular business logic can cause:
        - Uncontrolled resource consumption
        - Database bloat from retry records
        - Thread pool exhaustion
        
        Example (system thread only):
            # System monitoring thread - runs forever
            self.env['system.monitor'].asynch_exec(retry=-1, retry_delay=60000).poll_system_health()
        """
        return AsynchProxy(self, retry=retry, retry_delay=retry_delay)
    
    def await(self, retry=0, retry_delay=0):
        """
        Entry point for chained asynchronous execution with dependencies.
        Returns an AwaitProxy that allows building chains of dependent jobs.
        
        :param retry: Number of times to retry jobs on failure. Default: 0 (no retries)
        :param retry_delay: Delay in milliseconds before each execution/retry. Default: 0 (no delay)
        :return: AwaitProxy instance
        
        Examples:
            # Sequential execution: method2 runs after method1 completes
            recordset.await().method1().method2()
            
            # Parallel execution: method1 and method2 run simultaneously, 
            # method3 runs after both complete
            recordset.await().method1().await().method2().method3()
            
            # Complex chain: method1 and method2 run in parallel,
            # then method3 runs after both, then method4 runs after method3
            recordset.await().method1().await().method2().method3().method4()
            
            # With retries
            recordset.await(retry=3, retry_delay=500).process_data().send_email()
        """
        return AwaitProxy(self, retry=retry, retry_delay=retry_delay)
