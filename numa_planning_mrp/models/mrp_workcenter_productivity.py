from odoo import models, fields, api

class MrpWorkcenterProductivity(models.Model):
    _inherit = 'mrp.workcenter.productivity'

    numa_allocation_id = fields.Many2one('numa.planning.allocation', string='Numa Allocation')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.workorder_id:
                # Create corresponding Allocation with pln_state='wip'
                # Find a resource for this workcenter
                resource = self.env['numa.planning.resource'].search([
                    ('workcenter_id', '=', record.workcenter_id.id)
                ], limit=1)
                
                # If mrp.workcenter inherits numa.planning.resource, then workcenter IS a resource
                if not resource and record.workcenter_id:
                    resource = record.workcenter_id
                
                if resource:
                    # Get official scenario
                    scenario = self.env['numa.planning.scenario'].search([('is_official', '=', True)], limit=1)
                    if not scenario:
                         scenario = self.env['numa.planning.scenario'].create({'name': 'Official', 'is_official': True})

                    allocation = self.env['numa.planning.allocation'].create({
                        'node_id': record.workorder_id.id,
                        'resource_id': resource.id,
                        'scenario_id': scenario.id,
                        'start_date': record.date_start,
                        'end_date': record.date_end or fields.Datetime.now(),
                        'pln_state': 'wip' if not record.date_end else 'history'
                    })
                    record.numa_allocation_id = allocation.id
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'date_end' in vals:
            for record in self:
                if record.numa_allocation_id:
                    record.numa_allocation_id.write({
                        'end_date': record.date_end,
                        'pln_state': 'history'
                    })
        return res
