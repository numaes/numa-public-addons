from odoo import models, fields, api

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_view_supply_gantt(self):
        self.ensure_one()
        # Open Numa Allocations view filtered by this PO lines
        action = self.env["ir.actions.actions"]._for_xml_id("numa_planning.action_numa_planning_allocation")
        action['domain'] = [('node_id', 'in', self.order_line.ids)]
        # In a real scenario, this would open a specialized Gantt view
        return action
