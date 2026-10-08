"""Physical magnitudes on stock moves: what was actually shipped, not what the catalogue says."""

import logging
from collections import defaultdict

from odoo import api, fields, models
from odoo.tools.sql import create_index

_logger = logging.getLogger(__name__)

# Key in `cr.cache` for the arrivals already looked up while `_action_assign` runs.
_LAST_ARRIVAL_MEMO = 'numa_physical_product_stock.last_arrival'

UNIT_PER_TYPE = {
    'length': 'm',
    'width': 'm',
    'height': 'm',
    'surface': 'm2',
    'volume': 'm3',
    'weight': 'kg',
}


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    picking_weight = fields.Float('Weight', compute='_compute_picking_physicals')
    picking_volume = fields.Float('Volume', compute='_compute_picking_physicals')

    # This was an `@api.onchange` method doubling as the compute, with a
    # `@depends('move_line_ids')` that never looked at what was on the lines, and a
    # `button_validate` override that called it by hand to catch up. Depending on the
    # line totals keeps the figures current on every path, validation included.
    @api.depends('move_line_ids.total_weight', 'move_line_ids.total_volume')
    def _compute_picking_physicals(self):
        for picking in self:
            picking.picking_weight = sum(picking.move_line_ids.mapped('total_weight'))
            picking.picking_volume = sum(picking.move_line_ids.mapped('total_volume'))


class StockMove(models.Model):
    _inherit = 'stock.move'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface', related='product_id.surface', readonly=True)
    unit_weight = fields.Float(string='Unit Weight', related='product_id.weight', readonly=True)
    unit_volume = fields.Float(string='Unit Volume', related='product_id.volume', readonly=True)

    # These were plain stored fields kept up to date by an `@api.onchange`
    # method that `create` and `write` also called by hand. The `@api.depends` stacked
    # on the same method did nothing -- a depends only means something on a field's
    # compute -- so the totals went stale on every path the two overrides did not
    # cover, starting with a move line whose quantity changed.
    total_surface = fields.Float(string='Total Surface', compute='_compute_move_physicals', store=True)
    total_weight = fields.Float(string='Total Weight', compute='_compute_move_physicals', store=True)
    total_volume = fields.Float(string='Total Volume', compute='_compute_move_physicals', store=True)

    @api.depends('move_line_ids.total_surface', 'move_line_ids.total_weight',
                 'move_line_ids.total_volume', 'product_qty', 'product_id',
                 'unit_surface', 'unit_weight', 'unit_volume')
    def _compute_move_physicals(self):
        """What the move carries: its lines' figures, or the demand until it has any.

        The fallback reads `product_qty`, the demand in the product's own unit of
        measure. It used to read `quantity`, which is itself computed from the move
        lines -- so on a move with no lines, the only case the fallback exists
        for, it was always zero.
        """
        for move in self:
            lines = move.move_line_ids.filtered('product_id')
            if lines:
                move.total_surface = sum(lines.mapped('total_surface'))
                move.total_weight = sum(lines.mapped('total_weight'))
                move.total_volume = sum(lines.mapped('total_volume'))
            elif move.product_id:
                move.total_surface = move.unit_surface * move.product_qty
                move.total_weight = move.unit_weight * move.product_qty
                move.total_volume = move.unit_volume * move.product_qty
            else:
                move.total_surface = move.total_weight = move.total_volume = 0.0

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        """Seed a new move line with the dimensions of the last one that came in.

        A batch of slabs is not the catalogue slab. When the same product last arrived
        at this location, what it actually weighed is a better opening figure than the
        product record's, and the operator corrects it from there.
        """
        result = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        result.update(self._last_arrival_dimensions())
        return result

    def _last_arrival_dimensions(self):
        """The unit dimensions a new line of this move opens at.

        For a product tracked by serial number core calls `_prepare_move_line_vals`
        once per unit: confirming a purchase of 15000 meters asked the same question
        15000 times, each one a search over every line the product ever had, and the
        request outlived the worker's time limit. Inside `_action_assign` the answer
        cannot change -- nothing becomes done there -- so it is looked up once per
        product and location and kept until the assignment ends.
        """
        self.ensure_one()
        key = (self.product_id.id, self.location_id.id)
        memo = self.env.cr.cache.get(_LAST_ARRIVAL_MEMO)
        if memo is not None and key in memo:
            return memo[key]

        last_ingress = self.env['stock.move.line'].search([
            ('product_id', '=', self.product_id.id),
            ('location_dest_id', '=', self.location_id.id),
            ('state', '=', 'done'),
        ], order='write_date desc', limit=1)

        source = last_ingress or self
        dimensions = {
            'unit_weight': source.unit_weight,
            'unit_surface': source.unit_surface,
            'unit_volume': source.unit_volume,
        }
        if memo is not None:
            memo[key] = dimensions
        return dimensions

    def _action_assign(self, force_qty=False):
        """Carry the dimensions of this order's previous delivery onto the new one."""
        cache = self.env.cr.cache
        owns_memo = _LAST_ARRIVAL_MEMO not in cache
        if owns_memo:
            cache[_LAST_ARRIVAL_MEMO] = {}
        try:
            result = super()._action_assign(force_qty=force_qty)
            self._carry_previous_delivery_dimensions()
        finally:
            if owns_memo:
                cache.pop(_LAST_ARRIVAL_MEMO, None)
        return result

    def _carry_previous_delivery_dimensions(self):
        """The same search per line, and a write per line, did not scale with serials
        either: lines asking the same question share one search, and lines getting the
        same answer share one write."""
        move_line_model = self.env['stock.move.line']
        previous_delivery = {}
        line_ids_per_dimensions = defaultdict(list)

        for move in self:
            sale = move.picking_id.sale_id
            if not sale:
                continue
            for move_line in move.move_line_ids:
                key = (sale.id, move_line.product_id.id, move_line.location_id.id)
                if key not in previous_delivery:
                    previous_delivery[key] = move_line_model.search([
                        ('picking_id.sale_id', '=', sale.id),
                        ('product_id', '=', move_line.product_id.id),
                        ('location_dest_id', '=', move_line.location_id.id),
                        ('picking_id.state', '=', 'done'),
                    ], order='write_date desc', limit=1)
                last_ingress = previous_delivery[key]
                if last_ingress:
                    dimensions = (last_ingress.unit_weight,
                                  last_ingress.unit_surface,
                                  last_ingress.unit_volume)
                    line_ids_per_dimensions[dimensions].append(move_line.id)
                # With no previous delivery there is nothing to carry over, and
                # `_compute_unit_dimensions` has already seeded the line from the
                # product record.

        for (weight, surface, volume), line_ids in line_ids_per_dimensions.items():
            move_line_model.browse(line_ids).write({
                'unit_weight': weight,
                'unit_surface': surface,
                'unit_volume': volume,
            })


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)

    # These three were `related='product_id.<magnitude>', readonly=True` and not
    # stored, while `_prepare_move_line_vals` and `_action_assign` wrote to them and
    # `onchange_total_physicals` assigned to them. A write to a non-stored related field
    # lands in the cache and nowhere else: the value read back within the transaction
    # was the one just written, and the moment the cache was dropped it was the
    # product's again. So every per-line dimension this module exists to record -- what
    # the pallet actually weighed, what the previous delivery of the same order
    # weighed -- was silently discarded. They are stored now, seeded from the product
    # and writable, which is what the surrounding code always assumed.
    unit_surface = fields.Float(
        string='Unit Surface', compute='_compute_unit_dimensions',
        store=True, readonly=False)
    unit_weight = fields.Float(
        string='Unit Weight', compute='_compute_unit_dimensions',
        store=True, readonly=False)
    unit_volume = fields.Float(
        string='Unit Volume', compute='_compute_unit_dimensions',
        store=True, readonly=False)

    total_surface = fields.Float(
        string='Total Surface', compute='_compute_line_physicals',
        inverse='_inverse_total_surface', store=True, readonly=False)
    total_weight = fields.Float(
        string='Total Weight', compute='_compute_line_physicals',
        inverse='_inverse_total_weight', store=True, readonly=False)
    total_volume = fields.Float(
        string='Total Volume', compute='_compute_line_physicals',
        inverse='_inverse_total_volume', store=True, readonly=False)

    partner_id = fields.Many2one(
        'res.partner', string='Empresa', related='picking_id.partner_id',
        readonly=True, store=True)
    sale_order_id = fields.Many2one(
        'sale.order', string='Pedido', related='picking_id.sale_id',
        readonly=True, store=True)

    def init(self):
        super().init()
        # `_last_arrival_dimensions`: the last done line of a product into a location.
        # Only `product_id` was indexed, so each lookup read every line the product
        # ever had -- 63000 for a meter that is bought by the 15000 -- to keep none.
        create_index(
            self.env.cr, 'stock_move_line_numa_last_arrival_index', self._table,
            ['product_id', 'location_dest_id', 'write_date DESC'],
            where="state = 'done'")

    @api.depends('product_id')
    def _compute_unit_dimensions(self):
        """Open at the catalogue's figures; the operator corrects from there."""
        for move_line in self:
            move_line.unit_surface = move_line.product_id.surface
            move_line.unit_weight = move_line.product_id.weight
            move_line.unit_volume = move_line.product_id.volume

    def _normalized_qty(self):
        """The quantity in the product's own unit of measure.

        Which is what `quantity_product_uom` already is -- core computes it as
        `uom_id._compute_quantity(quantity, product.uom_id)`. This module converted it
        a second time, so a line entered in dozens reported twelve times the weight it
        carried: 2 dozen slabs of 10 kg came to 2880 kg instead of 240.
        """
        self.ensure_one()
        return self.quantity_product_uom

    @api.depends('product_id', 'quantity_product_uom',
                 'unit_surface', 'unit_weight', 'unit_volume')
    def _compute_line_physicals(self):
        for move_line in self:
            normalized_qty = move_line._normalized_qty()
            move_line.total_surface = normalized_qty * move_line.unit_surface
            move_line.total_weight = normalized_qty * move_line.unit_weight
            move_line.total_volume = normalized_qty * move_line.unit_volume

    # The operator weighs the pallet, not the piece. Entering a total is the usual way
    # in, and the per-unit figure is what follows from it.
    def _inverse_total_surface(self):
        self._set_unit_from_total('total_surface', 'unit_surface')

    def _inverse_total_weight(self):
        self._set_unit_from_total('total_weight', 'unit_weight')

    def _inverse_total_volume(self):
        self._set_unit_from_total('total_volume', 'unit_volume')

    def _set_unit_from_total(self, total_field, unit_field):
        for move_line in self:
            normalized_qty = move_line._normalized_qty()
            if normalized_qty:
                move_line[unit_field] = move_line[total_field] / normalized_qty
            else:
                move_line[total_field] = 0.0
