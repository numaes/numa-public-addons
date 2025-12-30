# -*- coding: utf-8 -*-
from odoo import models, fields, api
from collections import OrderedDict

class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'numa.planning.node']

    # numa_poly configuration
    # We depend on numa.planning.node to inherit its planning capabilities
    # and share the same ID space.
    _depend_models = OrderedDict([
        ('numa.planning.node', 'planning_node_id')
    ])

    # --- Odoo -> Numa Synchronization ---

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Map Odoo Deadline to Numa Constraint
            if 'date_deadline' in vals and 'pln_constraint_date' not in vals:
                vals['pln_constraint_date'] = vals['date_deadline']
                vals['pln_constraint_type'] = 'must_finish'
            
            # Map Odoo Planned Hours to Numa Effort
            if 'planned_hours' in vals and 'pln_effort_hours' not in vals:
                vals['pln_effort_hours'] = vals['planned_hours']
        
        tasks = super().create(vals_list)
        
        # Initial dependency sync
        for task in tasks:
            task._pln_sync_dependencies_to_links()
            
        return tasks

    def write(self, vals):
        # Map Odoo Deadline to Numa Constraint
        if 'date_deadline' in vals:
            vals['pln_constraint_date'] = vals['date_deadline']
            if vals['date_deadline']:
                vals['pln_constraint_type'] = 'must_finish'
            else:
                vals['pln_constraint_type'] = 'asap'

        # Map Odoo Planned Hours to Numa Effort
        if 'planned_hours' in vals:
            vals['pln_effort_hours'] = vals['planned_hours']

        res = super().write(vals)

        # Sync dependencies if modified
        if 'depend_on_ids' in vals:
            for task in self:
                task._pln_sync_dependencies_to_links()

        return res

    # --- Numa -> Odoo Synchronization ---

    @api.depends('pln_calc_start', 'pln_calc_end')
    def _compute_pln_dates(self):
        """
        Extend the base computation to also update Odoo's standard task dates.
        """
        super()._compute_pln_dates()
        for task in self:
            # We map Numa's calculated results back to Odoo's planned dates
            if task.pln_calc_start:
                task.planned_date_begin = task.pln_calc_start
            if task.pln_calc_end:
                task.date_end = task.pln_calc_end

    def _pln_sync_dependencies_to_links(self):
        """
        Translates Odoo's M2M 'depend_on_ids' into Numa's 'numa.planning.link' records.
        This allows Odoo dependencies to drive the CPM engine.
        """
        self.ensure_one()
        Link = self.env['numa.planning.link']
        # Clear existing links for this node as target (standard Odoo 'depend_on' means 'predecessors')
        existing_links = Link.search([('target_node_id', '=', self.id)])
        existing_links.unlink()

        for predecessor in self.depend_on_ids:
            Link.create({
                'source_node_id': predecessor.id,
                'target_node_id': self.id,
                'link_type': 'fs',  # Default to Finish-to-Start
                'lag_amount': 0.0,
            })
