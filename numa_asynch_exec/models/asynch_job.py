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
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='State', default='pending')

    @api.model
    def _recover_pending_jobs(self):
        pending_jobs = self.sudo().search([('state', '=', 'pending')])
        if pending_jobs:
            _logger.info("Retomando %s jobs asíncronos pendientes...", len(pending_jobs))
            # Import here to avoid circular dependency
            from ..utils import get_asynch_executor
            executor = get_asynch_executor()
            for job in pending_jobs:
                executor.submit(job._run_in_thread)

    def _run_in_thread(self):
        """Method to be executed in the ThreadPoolExecutor"""
        self.ensure_one()
        time.sleep(self.retry_delay / 1000.0)
        
        db_name = self.db_name
        registry = Registry(db_name)
        with registry.cursor() as cr:
            env = api.Environment(cr, self.uid.id, self.context or {})
            # Update state to running
            self.with_env(env).write({'state': 'running'})
            cr.commit()

            try:
                recordset = env[self.model_name].browse(self.res_ids)
                method = getattr(recordset, self.method_name)
                method(*self.args, **self.kwargs)
                
                # Mark as done
                self.with_env(env).write({'state': 'done'})
                cr.commit()
                
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
                    # Re-enqueue.
                    self.with_env(env).write({'state': 'failed'})
                    
                    # Import here to avoid circular dependency
                    from ..utils import get_asynch_executor
                    executor = get_asynch_executor()
                    cr.commit() 
                    executor.submit(new_job._run_in_thread)
                else:
                    self.with_env(env).write({'state': 'failed'})
                    cr.commit()
