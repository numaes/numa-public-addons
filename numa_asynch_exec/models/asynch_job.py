import time
import logging
from odoo import models, fields, api, SUPERUSER_ID
from odoo.modules.registry import Registry
try:
    from odoo.addons.numa_exceptions.models.exceptions import register_exception
except ImportError:
    def register_exception(*args, **kwargs):
        pass

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
    
    max_retries = fields.Integer(
        string='Max Retries',
        default=0,
        help="Maximum number of retries on failure. Use -1 for infinite retries "
             "(system threads only - see documentation). Default: 0 (no retries)"
    )
    retry_count = fields.Integer(string='Retry Count', default=0)
    retry_delay = fields.Integer(string='Retry Delay (ms)', default=0, help="Delay in milliseconds before execution/retry. Default: 0 (no delay)")
    
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
            from ..utils import get_asynch_executor, _run_in_thread
            executor = get_asynch_executor()
            for job in pending_jobs:
                executor.submit(_run_in_thread, job.id, job.db_name, job.context)


