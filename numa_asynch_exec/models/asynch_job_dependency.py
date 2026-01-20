"""
Job Dependency Model

Tracks dependencies between asynchronous jobs to enable sequential
and parallel execution patterns.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class NumaAsynchJobDependency(models.Model):
    """
    Job Dependency
    
    Represents a dependency relationship between two asynchronous jobs.
    The dependent job will only execute after all its dependencies are completed.
    """
    _name = 'numa.asynch.job.dependency'
    _description = 'Asynchronous Job Dependency'
    _rec_name = 'display_name'

    job_id = fields.Many2one(
        'numa.asynch.job',
        string='Dependent Job',
        required=True,
        ondelete='cascade',
        index=True,
        help='Job that depends on the completion of other jobs'
    )
    
    depends_on_id = fields.Many2one(
        'numa.asynch.job',
        string='Dependency',
        required=True,
        ondelete='cascade',
        index=True,
        help='Job that must complete before the dependent job can execute'
    )
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    @api.depends('job_id', 'depends_on_id')
    def _compute_display_name(self):
        """Compute display name"""
        for record in self:
            if record.job_id and record.depends_on_id:
                record.display_name = f"Job {record.job_id.id} depends on Job {record.depends_on_id.id}"
            else:
                record.display_name = "Dependency"

    @api.constrains('job_id', 'depends_on_id')
    def _check_no_self_dependency(self):
        """Prevent a job from depending on itself"""
        for record in self:
            if record.job_id.id == record.depends_on_id.id:
                raise ValidationError("A job cannot depend on itself")

    @api.constrains('job_id', 'depends_on_id')
    def _check_no_circular_dependency(self):
        """Prevent circular dependencies (basic check)"""
        for record in self:
            # Check if depends_on_id has a dependency chain that leads back to job_id
            visited = set()
            current = record.depends_on_id
            
            while current:
                if current.id == record.job_id.id:
                    raise ValidationError("Circular dependency detected")
                if current.id in visited:
                    break
                visited.add(current.id)
                
                # Find next dependency
                next_dep = self.search([
                    ('job_id', '=', current.id)
                ], limit=1)
                if next_dep:
                    current = next_dep.depends_on_id
                else:
                    break
