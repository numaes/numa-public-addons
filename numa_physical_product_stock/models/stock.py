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
            picking.move_lines.onchange_move_line_ids()
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

    @api.onchange('move_line_ids')
    @api.depends('move_line_ids')
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

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        move_line_model = self.env['stock.move.line']

        result = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)

        last_ingress = move_line_model.search([
            ('product_id', '=', self.product_id.id),
            ('location_dest_id', '=', self.location_id.id),
            ('state', '=', 'done'),
        ], order='write_date desc', limit=1)
        if last_ingress:
            unit_weight = last_ingress.unit_weight
            unit_surface = last_ingress.unit_surface
            unit_volume = last_ingress.unit_volume
        else:
            unit_weight = self.unit_weight
            unit_surface = self.unit_surface
            unit_volume = self.unit_volume

        result['unit_weight'] = unit_weight
        result['unit_surface'] = unit_surface
        result['unit_volume'] = unit_volume

        return result

    def _action_assign(self):
        move_line_model = self.env['stock.move.line']

        result = super()._action_assign()

        for move in self:
            for move_line in move.move_line_ids:
                if move.sale_line_id:
                    last_ingress = move_line_model.search([
                        ('product_id', '=', move_line.product_id.id),
                        ('location_dest_id', '=', move_line.location_id.id),
                        ('picking_id.state', '=', 'done'),
                        ('move_id.sale_line_id', '=', move.sale_line_id.id),
                    ], order='write_date desc', limit=1)
                else:
                    last_ingress = move_line_model.search([
                        ('product_id', '=', move_line.product_id.id),
                        ('location_dest_id', '=', move_line.location_id.id),
                        ('picking_id.state', '=', 'done'),
                    ], order='write_date desc', limit=1)

                if last_ingress:
                    move_line.write({
                        'unit_weight': last_ingress.unit_weight,
                        'unit_surface': last_ingress.unit_surface,
                        'unit_volume': last_ingress.unit_volume
                    })
                else:
                    move_line.write({
                        'unit_weight': move_line.product_id.weight,
                        'unit_surface': move_line.product_id.surface,
                        'unit_volume': move_line.product_id.volume
                    })
                move_line.flush()
                move_line.onchange_qty()

        return result

    def _action_done(self, cancel_backorder=False):
        move_line_model = self.env['stock.move.line']

        result = super()._action_done()

        for move in self:
            if move.exists():
                last_ingress = move.move_line_ids[0] if move.move_line_ids else None
                for next_move in move.move_dest_ids:
                    all_reserved = next_move.move_line_ids
                    if all_reserved and last_ingress:
                        all_reserved.write({
                            'unit_weight': last_ingress.unit_weight,
                            'unit_surface': last_ingress.unit_surface,
                            'unit_volume': last_ingress.unit_volume
                        })
                        all_reserved.flush()
                        all_reserved.onchange_qty()

        return result


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface')
    unit_weight = fields.Float(string='Unit Weight')
    unit_volume = fields.Float(string='Unit Volume')

    total_surface = fields.Float(string='Total Surface')
    total_weight = fields.Float(string='Total Weight')
    total_volume = fields.Float(string='Total Volume')

    @api.onchange('product_id', 'qty_done')
    @api.depends('product_id', 'qty_done')
    def onchange_qty(self):
        for move_line in self:
            normalized_qty = move_line.product_uom_id._compute_quantity(move_line.qty_done,
                                                                        move_line.product_id.uom_id) \
                if move_line.product_uom_id else move_line.qty_done
            move_line.total_surface = normalized_qty * move_line.unit_surface
            move_line.total_weight = normalized_qty * move_line.unit_weight
            move_line.total_volume = normalized_qty * move_line.unit_volume

    @api.onchange('total_weight', 'total_surface', 'total_volume', 'qty_done')
    @api.depends('total_weight', 'total_surface', 'total_volume', 'qty_done')
    def onchange_total_physicals(self):
        for move_line in self:
            normalized_qty = move_line.product_uom_id._compute_quantity(move_line.qty_done,
                                                                        move_line.product_id.uom_id) \
                if move_line.product_uom_id else move_line.qty_done
            if normalized_qty:
                if move_line.unit_weight != move_line.total_weight / normalized_qty:
                    move_line.unit_weight = move_line.total_weight / normalized_qty
                if move_line.unit_surface != move_line.total_surface / normalized_qty:
                    move_line.unit_surface = move_line.total_surface / normalized_qty
                if move_line.unit_volume != move_line.total_volume / normalized_qty:
                    move_line.unit_volume = move_line.total_volume / normalized_qty
            else:
                move_line.unit_weight = 0
                move_line.unit_surface = 0
                move_line.unit_volume = 0

    @api.model_create_multi
    def create(self, vals_list):
        new_move_lines = super().create(vals_list)
        new_move_lines.onchange_qty()
        return new_move_lines
