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

    picking_weight = fields.Float('Weight', compute='onchange_move_line_ids')
    picking_volume = fields.Float('Volume', compute='onchange_move_line_ids')

    @api.onchange('move_line_ids', 'move_line_ids_without_package')
    @api.depends('move_line_ids', 'move_line_ids_without_package')
    def onchange_move_line_ids(self):
        for move in self:
            picking_weight = 0.0
            picking_volume = 0.0
            for ml in move.move_line_ids:
                if ml.product_id:
                    picking_weight += ml.total_weight
                    picking_volume += ml.total_volume
            move.picking_weight = picking_weight
            move.picking_volume = picking_volume

    def button_validate(self):
        self.onchange_move_line_ids()
        for picking in self:
            picking.move_ids.onchange_move_line_ids()
        return super().button_validate()


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

    @api.onchange('move_line_ids', 'move_line_ids_without_package')
    @api.depends('move_line_ids', 'move_line_ids_without_package')
    def onchange_move_line_ids(self):
        for move in self:
            total_weight = 0.0
            total_volume = 0.0
            total_surface = 0.0
            for ml in move.move_line_ids:
                if ml.product_id:
                    total_weight += ml.total_weight
                    total_surface += ml.total_surface
                    total_volume += ml.total_volume
            move.total_weight = total_weight
            move.total_surface = total_surface
            move.total_volume = total_volume

    @api.model_create_multi
    def create(self, vals_list):
        new_moves = super().create(vals_list)
        new_moves.onchange_move_line_ids()
        return new_moves

    def write(self, vals):
        ret = super().write(vals)
        if 'move_line_ids' in vals:
            self.onchange_move_line_ids()
        return ret


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface', related='product_id.surface', readonly=True)
    unit_weight = fields.Float(string='Unit Weight', related='product_id.weight', readonly=True)
    unit_volume = fields.Float(string='Unit Volume', related='product_id.volume', readonly=True)

    total_surface = fields.Float(string='Total Surface')
    total_weight = fields.Float(string='Total Weight')
    total_volume = fields.Float(string='Total Volume')

    @api.onchange('product_id', 'qty_done')
    @api.depends('product_id', 'qty_done')
    def onchange_qty(self):
        for move_line in self:
            normalized_qty = move_line.product_uom_id._compute_quantity(move_line.qty_done,
                                                                        move_line.product_id.uom_id) \
                if move_line.product_uom_id else move_line.product_uom_qty
            move_line.total_surface = normalized_qty * move_line.unit_surface
            move_line.total_weight = normalized_qty * move_line.unit_weight
            move_line.total_volume = normalized_qty * move_line.unit_volume

    @api.model_create_multi
    def create(self, vals_list):
        new_move_lines = super().create(vals_list)
        new_move_lines.onchange_qty()
        return new_move_lines


