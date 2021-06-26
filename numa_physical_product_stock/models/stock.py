from odoo import fields, models, api

import logging
_logger = logging.getLogger(__name__)

UNIT_PER_TYPE = {
    'length': 'm',
    'width': 'm',
    'height': 'm',
    'surface': 'm2',
    'volume': 'm3',
    'weight': 'kg',
}

FIELD_NAME_PER_TYPE = {
    'length': 'product_length',
    'width': 'product_width',
    'height': 'product_height',
    'surface': 'surface',
    'volume': 'volume',
    'weight': 'weight',
}


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    picking_weight = fields.Float('Weight', compute='_compute_weight_volume')
    picking_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.onchange('move_lines')
    @api.depends('move_lines')
    def _compute_weight_volume(self):
        for picking in self:
            picking.picking_weight = 0.0
            picking.picking_volume = 0.0
            for move in picking.move_lines:
                picking.picking_weight += move.total_weight
                picking.picking_volume += move.total_volume


class StockMove(models.Model):
    _inherit = 'stock.move'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface', related='product_id.surface', readonly=True)
    unit_weight = fields.Float(string='Unit Weight', related='product_id.weight', readonly=True)
    unit_volume = fields.Float(string='Unit Volume', related='product_id.volume', readonly=True)

    total_surface = fields.Float(string='Total Surface')
    total_weight = fields.Float(string='Total Weight')
    total_volume = fields.Float(string='Total Volume')

    @api.onchange('product_id', 'product_qty', 'product_uom_qty')
    @api.depends('product_id', 'product_qty', 'product_uom_qty')
    def onchange_qty(self):
        for move in self:
            normalized_qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id) \
                if move.product_uom else move.product_uom_qty
            move.total_surface = normalized_qty * move.unit_surface
            move.total_weight = normalized_qty * move.unit_weight
            move.total_volume = normalized_qty * move.unit_volume

    @api.model_create_multi
    def create(self, vals_list):
        new_moves = super().create(vals_list)
        new_moves.onchange_qty()
        return new_moves


