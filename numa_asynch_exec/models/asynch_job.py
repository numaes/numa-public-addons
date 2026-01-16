import time
import logging
from odoo import models, fields, api, Registry, SUPERUSER_ID
from odoo.addons.numa_exceptions.models.exceptions import register_exception

_logger = logging.getLogger(__name__)

class NumaAsynchJob(models.Model):
    _name = 'numa.asynch.job'
    _description = 'Asynchronous Job'

    db_name = fields.Char(string='Database Name')
    model_name = fields.Char(string='Model Name')
    res_ids = fields.Json(string='Resource IDs')
    method_name = fields.Char(string='Method Name')
    args = fields.Json(string='Arguments')
    kwargs = fields.Json(string='Keyword Arguments')
    context = fields.Json(string='Context')
    uid = fields.Many2one('res.users', string='User')
    
    max_retries = fields.Integer(string='Max Retries', default=0)
    retry_count = fields.Integer(string='Retry Count', default=0)
    retry_delay = fields.Integer(string='Retry Delay (ms)', default=100)
    
    state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='State', default='pending')

    def _run_in_thread(self):
        """Method to be executed in the ThreadPoolExecutor"""
        self.ensure_one()
        time.sleep(self.retry_delay / 1000.0)
        
        db_name = self.db_name
        registry = Registry(db_name)
        with registry.cursor() as cr:
            env = api.Environment(cr, self.uid.id, self.context or {})
            try:
                recordset = env[self.model_name].browse(self.res_ids)
                method = getattr(recordset, self.method_name)
                method(*self.args, **self.kwargs)
                
                # Mark as done
                # We need a new environment/cursor to update the job status if we want it persisted
                # or we can update it in the current cursor and commit.
                self.with_env(env).write({'state': 'done'})
                
            except Exception as e:
                cr.rollback()
                # Log exception using numa_exceptions
                register_exception(
                    'numa_asynch_exec',
                    self.method_name,
                    {'args': self.args, 'kwargs': self.kwargs},
                    db_name,
                    self.uid.id,
                    e
                )
                
                if self.retry_count < self.max_retries:
                    # Create a new retry job
                    new_job = self.sudo().copy({
                        'retry_count': self.retry_count + 1,
                        'state': 'pending',
                    })
                    # Re-enqueue. We need to do this after the current transaction if we want to be safe, 
                    # but since we are already in a thread, we can just trigger it.
                    # Wait, the current job in DB is still 'pending' or 'failed'.
                    self.with_env(env).write({'state': 'failed'})
                    
                    # Import here to avoid circular dependency
                    from ..utils import get_asynch_executor
                    executor = get_asynch_executor()
                    # We need to make sure the new_job is committed before it runs,
                    # but here we are in a separate cursor.
                    # Actually, we should commit the 'failed' state and the 'new_job' creation.
                    cr.commit() 
                    executor.submit(new_job._run_in_thread)
                else:
                    self.with_env(env).write({'state': 'failed'})
                    cr.commit()
