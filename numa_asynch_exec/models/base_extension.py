from odoo import models, api
from ..utils import get_asynch_executor

class AsynchProxy:
    """
    A proxy object that intercepts method calls on a recordset and
    enqueues them for asynchronous execution.
    """
    def __init__(self, recordset, retry=0, retry_delay=100):
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
            job_vals = {
                'db_name': self.recordset.env.cr.dbname,
                'model_name': self.recordset._name,
                'res_ids': self.recordset.ids,
                'method_name': name,
                'args': args,
                'kwargs': kwargs,
                'context': self.recordset.env.context,
                'uid': self.recordset.env.uid,
                'max_retries': self.retry,
                'retry_delay': self.retry_delay,
            }
            # Create the job record in sudo mode to ensure persistence
            job = self.recordset.env['numa.asynch.job'].sudo().create(job_vals)
            
            # Register a hook to submit the job only after the current transaction is committed.
            # This ensures that the job record is visible to the background thread.
            def _submit_job():
                executor = get_asynch_executor()
                executor.submit(job._run_in_thread)

            self.recordset.env.cr.after_commit(_submit_job)
            return True

        return _asynch_call

class Base(models.AbstractModel):
    """
    Extension of the Odoo 'base' model to provide asynchronous execution capabilities
    to all models in the system.
    """
    _inherit = 'base'

    def asynch_exec(self, retry=0, retry_delay=100):
        """
        Entry point for asynchronous execution. Returns an AsynchProxy.
        
        :param retry: Number of times to retry the job on failure.
        :param retry_delay: Delay in milliseconds before each execution/retry.
        :return: AsynchProxy instance
        
        Example:
            recordset.asynch_exec(retry=3).some_heavy_method(arg1)
        """
        return AsynchProxy(self, retry=retry, retry_delay=retry_delay)
