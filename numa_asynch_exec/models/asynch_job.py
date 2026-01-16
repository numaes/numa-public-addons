import time
import logging
from odoo import models, fields, api, Registry, SUPERUSER_ID
from odoo.addons.numa_exceptions.models.exceptions import register_exception

_logger = logging.getLogger(__name__)

class NumaAsynchJob(models.Model):
    """
    Model to persist and manage asynchronous tasks.
    It stores all necessary metadata to recreate the execution environment
    in a separate thread.
    """
    _name = 'numa.asynch.job'
    _description = 'Asynchronous Job'

    db_name = fields.Char(string='Database Name', help="Target database for execution")
    model_name = fields.Char(string='Model Name', help="Target Odoo model")
    res_ids = fields.Json(string='Resource IDs', help="IDs of the records to execute the method on")
    method_name = fields.Char(string='Method Name', help="Name of the method to call")
    args = fields.Json(string='Arguments', help="Positional arguments for the method")
    kwargs = fields.Json(string='Keyword Arguments', help="Keyword arguments for the method")
    context = fields.Json(string='Context', help="Serialized environment context")
    uid = fields.Many2one('res.users', string='User', help="User to impersonate during execution")
    
    max_retries = fields.Integer(string='Max Retries', default=0)
    retry_count = fields.Integer(string='Retry Count', default=0)
    retry_delay = fields.Integer(string='Retry Delay (ms)', default=100)
    
    state = fields.Selection([
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='State', default='pending', index=True)

    @api.model
    def _recover_pending_jobs(self):
        """
        Retrieves all jobs in 'pending' state and re-submits them to the executor.
        Typically called during module post-init to recover tasks interrupted
        by a server restart or crash.
        """
        pending_jobs = self.sudo().search([('state', '=', 'pending')])
        if pending_jobs:
            _logger.info("Recovering %s pending asynchronous jobs...", len(pending_jobs))
            # Import here to avoid circular dependency
            from ..utils import get_asynch_executor
            executor = get_asynch_executor()
            for job in pending_jobs:
                executor.submit(job._run_in_thread)

    def _run_in_thread(self):
        """
        Orchestrates the asynchronous execution of the job in a separate thread.
        Handles environment recreation, execution, exception logging, and retries.
        """
        self.ensure_one()
        # Respect configured delay before starting
        time.sleep(self.retry_delay / 1000.0)
        
        db_name = self.db_name
        registry = Registry(db_name)
        with registry.cursor() as cr:
            # Recreate environment with original user and context
            env = api.Environment(cr, self.uid.id, self.context or {})
            
            # Update state to running and commit immediately to avoid re-recovery
            self.with_env(env).write({'state': 'running'})
            cr.commit()

            try:
                # Browse records and execute method
                recordset = env[self.model_name].browse(self.res_ids)
                method = getattr(recordset, self.method_name)
                method(*self.args, **self.kwargs)
                
                # Mark as successfully completed
                self.with_env(env).write({'state': 'done'})
                cr.commit()
                
            except Exception as e:
                cr.rollback()
                # Log the exception for traceability via numa_exceptions module
                register_exception(
                    'numa_asynch_exec',
                    self.method_name,
                    {'args': self.args, 'kwargs': self.kwargs},
                    db_name,
                    self.uid.id,
                    e
                )
                
                if self.retry_count < self.max_retries:
                    # Logic for automatic retry: create a copy of the job with incremented retry count
                    new_job = self.sudo().copy({
                        'retry_count': self.retry_count + 1,
                        'state': 'pending',
                    })
                    # Mark current job as failed
                    self.with_env(env).write({'state': 'failed'})
                    
                    from ..utils import get_asynch_executor
                    executor = get_asynch_executor()
                    # Commit failure and new job creation before re-queueing
                    cr.commit() 
                    executor.submit(new_job._run_in_thread)
                else:
                    # Final failure if no retries left
                    self.with_env(env).write({'state': 'failed'})
                    cr.commit()
