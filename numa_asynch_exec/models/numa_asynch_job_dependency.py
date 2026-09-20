# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NumaAsynchJobDependency(models.Model):
    """One edge of the dependency graph: ``job_id`` waits for ``depends_on_id``."""
    _name = 'numa.asynch.job.dependency'
    _description = "Asynchronous Job Dependency"
    _order = 'job_id, id'

    job_id = fields.Many2one(
        'numa.asynch.job', string="Dependent Job", required=True, ondelete='cascade', index=True,
        help="Job that waits")
    depends_on_id = fields.Many2one(
        'numa.asynch.job', string="Dependency", required=True, ondelete='cascade', index=True,
        help="Job that must finish first")

    _unique_edge = models.UniqueIndex("(job_id, depends_on_id)")

    @api.depends('job_id', 'depends_on_id')
    def _compute_display_name(self):
        for record in self:
            record.display_name = self.env._(
                "Job %(job)s depends on job %(dependency)s",
                job=record.job_id.id, dependency=record.depends_on_id.id)

    @api.constrains('job_id', 'depends_on_id')
    def _check_no_cycle(self):
        """Refuse an edge that would let a job wait for itself.

        A cycle never resolves: every job in it stays in ``waiting`` forever,
        and nothing in the system would ever say why.
        """
        for record in self:
            if record.job_id == record.depends_on_id:
                raise ValidationError(self.env._("A job cannot depend on itself."))
            # Walk everything the new dependency itself waits for: reaching
            # the dependent job back means the edge closes a loop.
            seen = set()
            frontier = record.depends_on_id.ids
            while frontier:
                if record.job_id.id in frontier:
                    raise ValidationError(self.env._(
                        "This dependency would create a cycle: job %(job)s already waits, "
                        "directly or not, for job %(dependency)s.",
                        job=record.depends_on_id.id, dependency=record.job_id.id))
                seen.update(frontier)
                edges = self.search([('job_id', 'in', frontier)])
                frontier = [job_id for job_id in set(edges.depends_on_id.ids) if job_id not in seen]
