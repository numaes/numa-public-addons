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
        ('waiting', 'Waiting for Dependencies'),
    ], string='State', default='pending', index=True)
    
    dependency_ids = fields.One2many(
        'numa.asynch.job.dependency',
        'job_id',
        string='Dependencies',
        help='Jobs that must complete before this job can execute'
    )
    
    dependent_job_ids = fields.One2many(
        'numa.asynch.job.dependency',
        'depends_on_id',
        string='Dependent Jobs',
        help='Jobs that depend on this job'
    )
    
    has_dependencies = fields.Boolean(
        string='Has Dependencies',
        compute='_compute_has_dependencies',
        help='True if this job has dependencies that must complete first'
    )
    
    all_dependencies_done = fields.Boolean(
        string='All Dependencies Done',
        compute='_compute_all_dependencies_done',
        help='True if all dependency jobs are in done state'
    )

    @api.depends('dependency_ids')
    def _compute_has_dependencies(self):
        """Compute if job has dependencies"""
        for record in self:
            record.has_dependencies = bool(record.dependency_ids)

    @api.depends('dependency_ids.depends_on_id.state')
    def _compute_all_dependencies_done(self):
        """Compute if all dependencies are done"""
        for record in self:
            if not record.dependency_ids:
                record.all_dependencies_done = True
            else:
                all_done = all(
                    dep.depends_on_id.state == 'done'
                    for dep in record.dependency_ids
                )
                record.all_dependencies_done = all_done

    @api.model
    def _recover_pending_jobs(self):
        """
        Retrieves all jobs in 'pending' or 'waiting' state and re-submits them to the executor.
        Typically called during module post-init to recover tasks interrupted
        by a server restart or crash.
        """
        pending_jobs = self.sudo().search([
            ('state', 'in', ['pending', 'waiting'])
        ])
        if pending_jobs:
            _logger.info("Recovering %s pending asynchronous jobs...", len(pending_jobs))
            # Import here to avoid circular dependency
            from ..utils import get_asynch_executor, _run_in_thread
            executor = get_asynch_executor()
            for job in pending_jobs:
                # Check dependencies before submitting
                if job.has_dependencies and not job.all_dependencies_done:
                    job.write({'state': 'waiting'})
                else:
                    executor.submit(_run_in_thread, job.id, job.db_name, job.context)
    
    def _check_and_trigger_dependents(self):
        """
        Check if any dependent jobs can now execute (all their dependencies are done).
        Called after a job completes successfully.
        """
        for record in self:
            for dep_rel in record.dependent_job_ids:
                dependent_job = dep_rel.job_id
                if dependent_job.state == 'waiting' and dependent_job.all_dependencies_done:
                    # All dependencies are done, trigger execution
                    _logger.info(
                        'Job %s dependencies satisfied, triggering execution',
                        dependent_job.id
                    )
                    dependent_job.write({'state': 'pending'})
                    from ..utils import get_asynch_executor, _run_in_thread
                    executor = get_asynch_executor()
                    executor.submit(
                        _run_in_thread,
                        dependent_job.id,
                        dependent_job.db_name,
                        dependent_job.context
                    )


