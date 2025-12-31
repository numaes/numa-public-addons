from odoo import models, fields, api

class MrpWorkorder(models.Model):
    _inherit = ['mrp.workorder', 'numa.planning.node']

    # Poly Depends: _depend_models = {'mrp.workorder': 'workorder_id'}.
    # This might be for numa_poly, but numa_planning_node also uses it?
    # Actually, numa.planning.node inherits from numa.poly.mixin
    _depend_models = {'mrp.workorder': 'workorder_id'}

    # Field Mapping (Bi-directional):
    # duration_expected <-> pln_effort_hours.
    # date_planned_start <-> pln_calc_start.
    # date_planned_finished <-> pln_calc_end.
    
    # Odoo mrp.workorder:
    # duration_expected is Float (minutes)
    # date_planned_start is Datetime
    # date_planned_finished is Datetime
    
    # Numa numa.planning.node:
    # pln_effort_hours is Float (hours)
    # pln_calc_start is Datetime
    # pln_calc_end is Datetime

    pln_effort_hours = fields.Float(compute='_compute_pln_effort_hours', inverse='_inverse_pln_effort_hours', store=True)
    pln_calc_start = fields.Datetime(compute='_compute_pln_calc_start', inverse='_inverse_pln_calc_start', store=True)
    pln_calc_end = fields.Datetime(compute='_compute_pln_calc_end', inverse='_inverse_pln_calc_end', store=True)

    @api.depends('duration_expected')
    def _compute_pln_effort_hours(self):
        for wo in self:
            wo.pln_effort_hours = wo.duration_expected / 60.0

    def _inverse_pln_effort_hours(self):
        for wo in self:
            wo.duration_expected = wo.pln_effort_hours * 60.0

    @api.depends('date_planned_start')
    def _compute_pln_calc_start(self):
        for wo in self:
            wo.pln_calc_start = wo.date_planned_start

    def _inverse_pln_calc_start(self):
        for wo in self:
            wo.date_planned_start = wo.pln_calc_start

    @api.depends('date_planned_finished')
    def _compute_pln_calc_end(self):
        for wo in self:
            wo.pln_calc_end = wo.date_planned_finished

    def _inverse_pln_calc_end(self):
        for wo in self:
            wo.date_planned_finished = wo.pln_calc_end

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._sync_numa_dependencies()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals and vals['state'] == 'ready':
            for record in self:
                record._sync_numa_dependencies()
        return res

    def _sync_numa_dependencies(self):
        for wo in self:
            if not wo.production_id:
                continue
            
            # Identify the previous WO based on sequence.
            # Workorders in the same MO, sorted by sequence.
            workorders = wo.production_id.workorder_ids.sorted(key=lambda r: (r.sequence, r.id))
            
            wo_list = workorders.ids
            current_index = wo_list.index(wo.id)
            
            if current_index > 0:
                prev_wo_id = wo_list[current_index - 1]
                prev_wo = self.env['mrp.workorder'].browse(prev_wo_id)
                
                # Create/Update a numa.planning.link (Type FS) connecting Previous WO -> Current WO.
                # Find existing link
                link = self.env['numa.planning.link'].search([
                    ('source_node_id', '=', prev_wo.numa_planning_node_id.id if hasattr(prev_wo, 'numa_planning_node_id') else False), # This might be tricky if we don't have a direct link
                    ('target_node_id', '=', wo.numa_planning_node_id.id if hasattr(wo, 'numa_planning_node_id') else False),
                ], limit=1)
                
                # Since numa.planning.node is inherited by mrp.workorder, 
                # and numa.poly.mixin is used, we should use the base model id.
                
                # Wait, numa.planning.link uses source_node_id and target_node_id which are Many2one('numa.planning.node')
                # If mrp.workorder inherits numa.planning.node, then a record of mrp.workorder IS a record of numa.planning.node (in Odoo inheritance)
                # But numa.planning.node is _name = 'numa.planning.node'. Inheriting it usually means delegation or mixin.
                # If it's _inherit = ['numa.planning.node'], it's class inheritance.
                
                source_node = prev_wo
                target_node = wo
                
                existing_link = self.env['numa.planning.link'].search([
                    ('source_node_id', '=', source_node.id),
                    ('target_node_id', '=', target_node.id),
                    ('link_type', '=', 'fs')
                ], limit=1)
                
                if not existing_link:
                    self.env['numa.planning.link'].create({
                        'source_node_id': source_node.id,
                        'target_node_id': target_node.id,
                        'link_type': 'fs'
                    })

    def action_view_numa_planning(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("numa_planning.action_numa_planning_allocation")
        action['domain'] = [('node_id', '=', self.id)]
        return action

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def action_view_numa_planning(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("numa_planning.action_numa_planning_allocation")
        action['domain'] = [('node_id', 'in', self.workorder_ids.ids)]
        # We might want to open a Gantt view if available, but for now let's use the Allocation view
        # filtered by this MO's work orders.
        return action
