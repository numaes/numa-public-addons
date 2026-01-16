from odoo import models, api
from ..utils import get_asynch_executor

class AsynchProxy:
    def __init__(self, recordset, retry=0, retry_delay=100):
        self.recordset = recordset
        self.retry = retry
        self.retry_delay = retry_delay

    def __getattr__(self, name):
        def _asynch_call(*args, **kwargs):
            # Create job record
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
            job = self.recordset.env['numa.asynch.job'].sudo().create(job_vals)
            
            # Register after_commit
            def _submit_job():
                executor = get_asynch_executor()
                executor.submit(job._run_in_thread)

            self.recordset.env.cr.after_commit(_submit_job)
            return True

        return _asynch_call

class Base(models.AbstractModel):
    _inherit = 'base'

    def asynch_exec(self, retry=0, retry_delay=100):
        return AsynchProxy(self, retry=retry, retry_delay=retry_delay)
