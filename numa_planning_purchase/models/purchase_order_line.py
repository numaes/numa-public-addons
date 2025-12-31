from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrderLine(models.Model):
    _inherit = ['purchase.order.line', 'numa.planning.node']

    # Field Mapping (Bi-directional):
    # pln_constraint_date <-> date_planned (Arrival Date).
    # pln_effort_hours <-> customer_lead (from Product) OR Computed AI Lead Time.
    # resource_id <-> order_id.partner_id.

    pln_constraint_date = fields.Datetime(compute='_compute_pln_constraint_date', inverse='_inverse_pln_constraint_date', store=True)
    pln_effort_hours = fields.Float(compute='_compute_pln_effort_hours', inverse='_inverse_pln_effort_hours', store=True)
    
    # numa.planning.node has resource_id? 
    # Let me check numa_planning.py again. 
    # Actually, allocations link nodes to resources. 
    # But for simple nodes, we might want a preferred resource.
    # numa.planning.node doesn't have a direct resource_id in the abstract model.
    # But requirements say resource_id <-> order_id.partner_id.
    # I'll add the field to this model.
    pln_resource_id = fields.Many2one('numa.planning.resource', compute='_compute_pln_resource_id', store=True)

    @api.depends('date_planned')
    def _compute_pln_constraint_date(self):
        for line in self:
            line.pln_constraint_date = line.date_planned

    def _inverse_pln_constraint_date(self):
        for line in self:
            line.date_planned = line.pln_constraint_date

    @api.depends('product_id', 'product_id.seller_ids')
    def _compute_pln_effort_hours(self):
        for line in self:
            # Fallback to product's lead time converted to hours
            # customer_lead is usually days.
            lead_days = line.product_id.purchase_delay or 0
            line.pln_effort_hours = lead_days * 24.0

    def _inverse_pln_effort_hours(self):
        # We don't necessarily want to write back to purchase_delay on the product
        pass

    @api.depends('order_id.partner_id')
    def _compute_pln_resource_id(self):
        for line in self:
            # The partner inherited numa.planning.resource, so the ID should match if it's delegation or same ID.
            # In Odoo, if we use _inherit = ['res.partner', 'numa.planning.resource'], 
            # then a res.partner record IS a numa.planning.resource record.
            line.pln_resource_id = line.order_id.partner_id.id

    def _compute_pln_ai_score(self):
        """
        AI Hooks Implementation:
        Override _compute_pln_ai_score:
        Implement logic to fetch data from numa_ai if installed.
        Fallback: Calculate score based on order_id.amount_total or Urgency.

        DETAILED COMMENT BLOCK FOR AI TRAINING:
        To feed historical consumption data into the AI Model and adjust pln_priority:
        1. Extract 'stock.move' history for the product linked to this POL.
        2. Analyze 'date' and 'quantity' of past consumptions (outgoing moves).
        3. Identify seasonality patterns and average lead time deviation from this supplier.
        4. Calculate the 'Service Level Risk': If (Current Stock + Incoming) < Forecasted Demand during Lead Time.
        5. Pass these features to the AI Agent (e.g. via numa_ai.predict) to return a priority score.
        6. Higher scores should be assigned to POLs whose delay would cause a stock-out in critical production orders.
        """
        for line in self:
            score = 0.0
            # Try to use numa_ai if available
            if hasattr(self.env['numa.planning.strategy'], 'ai_predict_score'):
                try:
                    score = self.env['numa.planning.strategy'].ai_predict_score(line)
                except Exception as e:
                    _logger.warning("AI Scoring failed, using fallback: %s", e)
            
            if not score:
                # Fallback logic
                # Urgency: if date_planned is close to now
                # Value: order_id.amount_total
                amount = line.order_id.amount_total
                days_to_arrival = (line.date_planned - fields.Datetime.now()).days if line.date_planned else 30
                urgency = 1.0 / (max(days_to_arrival, 1))
                score = (amount / 1000.0) + (urgency * 100.0)
            
            line.pln_ai_score = score

    def _find_downstream_demand(self):
        """
        Logic: If this purchase was created by a specific Stock Move / Procurement Group linked to a MO or SO, 
        create a numa.planning.link (FS).
        """
        for line in self:
            # Find related stock moves (incoming)
            moves = line.move_ids
            for move in moves:
                # Find the move that triggered this one (demand)
                # In Odoo, move.move_dest_ids are the moves that depend on this move.
                for dest_move in move.move_dest_ids:
                    # Check if dest_move is linked to a Work Order (MO) or a Sale Order
                    target_node = False
                    
                    # If it's for a MO
                    if dest_move.workorder_id:
                        target_node = dest_move.workorder_id
                    elif dest_move.production_id:
                        # Link to the first workorder or the production itself if it's a node
                        if dest_move.production_id.workorder_ids:
                            target_node = dest_move.production_id.workorder_ids.sorted()[0]
                    
                    # If it's for a SO
                    elif dest_move.sale_line_id:
                        # We might need numa_planning_sale for this, 
                        # but let's assume sale.order.line will also be a node.
                        target_node = dest_move.sale_line_id

                    if target_node:
                        # Create Link FS: Purchase -> Demand
                        self.env['numa.planning.link'].create({
                            'source_node_id': line.id,
                            'target_node_id': target_node.id,
                            'link_type': 'fs'
                        })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            line._find_downstream_demand()
        return lines
