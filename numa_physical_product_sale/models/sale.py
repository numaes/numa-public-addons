import logging

from odoo import fields, models, api

_logger = logging.getLogger(__name__)

UNIT_PER_TYPE = {
    'length': 'm',
    'width': 'm',
    'height': 'm',
    'surface': 'm²',
    'volume': 'm³',
    'weight': 'kg',
}

# The three price bases that also have a total on the line, which a user may type
# over when the physical piece is not what the product record says. For those, the
# line's own figure is what the price is applied to; for the rest there is nothing to
# override and the product answers.
OVERRIDABLE_TOTAL_PER_BASE = {
    'surface': 'total_surface',
    'weight': 'total_weight',
    'volume': 'total_volume',
}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    so_weight = fields.Float('Weight', compute='_compute_weight_volume')
    so_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.depends('order_line.total_weight', 'order_line.total_volume')
    def _compute_weight_volume(self):
        for so in self:
            so.so_weight = 0.0
            so.so_volume = 0.0
            for line in so.order_line:
                so.so_weight += line.total_weight
                so.so_volume += line.total_volume

    # [20.0] Two methods were removed from here, both of them overriding core methods
    # that no longer exist.
    #
    # `_get_real_price_currency` was dropped from `sale.order` in 17.0. This override
    # returned `(0.0, False)` -- had core still called it, every line would have been
    # priced at zero.
    #
    # `update_prices` was renamed `_recompute_prices` in 17.0, and the
    # `show_update_pricelist` field it wrote went with it. The body called
    # `product_id_change()` and `compute_totals()` by hand to refill the physical
    # quantities; those are computed fields now, so a pricelist change refills them by
    # itself and there is nothing left for this method to do.


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface', related='product_id.surface', readonly=True)
    unit_weight = fields.Float(string='Unit Weight', related='product_id.weight', readonly=True)
    unit_volume = fields.Float(string='Unit Volume', related='product_id.volume', readonly=True)

    # [20.0] These four were plain stored fields, filled only by `@api.onchange`
    # handlers -- so they were filled only when a human typed into the form. A line
    # created any other way (a quotation template, an import, the website shop, an API
    # call, duplicating an order) kept them at zero. And `price_qty` is what
    # `_prepare_base_line_for_taxes_computation` puts on the tax base, so a slab priced
    # by weight was invoiced by the unit: four slabs at 3.00/kg came to 12.00 instead
    # of 150.00, with nothing in the log and a plausible-looking number on the invoice.
    #
    # They are computed fields now. `store=True` keeps them queryable and reportable;
    # `readonly=False` on the totals keeps the one thing the onchange allowed, which is
    # typing over a derived figure when the physical piece is not what the product
    # record says.
    total_surface = fields.Float(
        string='Total Surface', compute='_compute_physical_totals',
        store=True, readonly=False)
    total_weight = fields.Float(
        string='Total Weight', compute='_compute_physical_totals',
        store=True, readonly=False)
    total_volume = fields.Float(
        string='Total Volume', compute='_compute_physical_totals',
        store=True, readonly=False)

    price_qty = fields.Float(
        string='Price Qty', compute='_compute_price_qty', store=True,
        help="The quantity the price is applied to: the physical magnitude named by "
             "the product's price base, or the ordered quantity when it prices "
             "normally.")
    unit_price_uom_id = fields.Many2one(
        'uom.uom', 'Price UoM', compute='_compute_unit_price_uom', store=True)

    @api.depends('product_id', 'product_id.price_base', 'product_id.uom_id')
    def _compute_unit_price_uom(self):
        uom_model = self.env['uom.uom']

        for sol in self:
            if sol.product_id:
                if sol.product_id.price_base == 'normal':
                    sol.unit_price_uom_id = sol.product_id.uom_id.id
                else:
                    sol.unit_price_uom_id = uom_model.search(
                        [('name', '=', UNIT_PER_TYPE[sol.product_id.price_base])],
                        limit=1
                    ).id
            else:
                sol.unit_price_uom_id = False

    @api.depends('product_uom_qty', 'product_uom_id', 'product_id',
                 'unit_surface', 'unit_weight', 'unit_volume')
    def _compute_physical_totals(self):
        for sol in self:
            normalized_qty = sol.product_uom_id._compute_quantity(sol.product_uom_qty, sol.product_id.uom_id) \
                if sol.product_uom_id else sol.product_uom_qty
            sol.total_surface = normalized_qty * sol.unit_surface
            sol.total_weight = normalized_qty * sol.unit_weight
            sol.total_volume = normalized_qty * sol.unit_volume

    @api.depends('total_surface', 'total_weight', 'total_volume', 'product_uom_qty',
                 'product_uom_id', 'product_id', 'product_id.price_base',
                 'unit_length', 'unit_width', 'unit_height')
    def _compute_price_qty(self):
        # The six-way branch that used to be here is `product._get_price_qty`, which
        # `numa_physical_product` centralises for exactly these three bridges. The only
        # thing that is not the product's answer is a total the user typed over.
        for sol in self:
            if not sol.product_id:
                sol.price_qty = sol.product_uom_qty
                continue
            total_field = OVERRIDABLE_TOTAL_PER_BASE.get(sol.product_id.price_base)
            if total_field:
                sol.price_qty = sol[total_field]
            else:
                sol.price_qty = sol.product_id._get_price_qty(
                    sol.product_uom_qty, uom=sol.product_uom_id)

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        """Tax the physical quantity, not the number of units.

        [20.0] This used to be a fork of `_compute_amount`: it called
        `tax_id.compute_all` itself and wrote `price_subtotal`, `price_total` and
        `price_tax` by hand. Two reasons that had to go. `tax_id` became `tax_ids`, so
        the `@api.depends` named a field that does not exist and the module could not
        install. And Odoo 20 rebuilt the tax engine -- rounding per document, tax
        details, global discounts, down payments -- so a fork written against the old
        one would have computed different numbers from the rest of the invoice.

        The hook hands core a base line and lets it compute. What this module changes is
        one number in that line.
        """
        values = super()._prepare_base_line_for_taxes_computation(**kwargs)
        if self.product_id.price_base != 'normal' and self.price_qty:
            values['quantity'] = self.price_qty
        return values

    @api.depends('price_qty')
    def _compute_amount(self):
        """Recompute the amounts when the physical quantity moves.

        Core's `_compute_amount` depends on `product_uom_qty`; ours is driven by
        `price_qty`, which core has never heard of. Declaring the extra dependency here
        and delegating is what keeps the totals in step without forking the computation.
        """
        return super()._compute_amount()

    def _prepare_invoice_line(self, **optional_values):
        """
        Prepare the dict of values to create the new invoice line for a sales order line.

        """
        self.ensure_one()

        new_optional_values = dict(optional_values.items())
        product = self.product_id
        if product.price_base != 'normal':
            new_optional_values['quantity'], new_optional_values['price_qty'] = self._get_qty_to_invoice()
            new_optional_values['unit_price_uom_id'] = self._get_price_uom_id()
        else:
            new_optional_values['quantity'] = self.qty_to_invoice
            new_optional_values['price_qty'] = self.qty_to_invoice
            new_optional_values['unit_price_uom_id'] = self._get_price_uom_id()

        return super()._prepare_invoice_line(**new_optional_values)

    def _get_price_uom_id(self):
        uom_model = self.env['uom.uom']

        self.ensure_one()

        if not self.display_type and self.product_id:
            if self.product_id.price_base == 'normal':
                return self.product_id.uom_id.id
            else:
                return uom_model.search(
                    [('name', '=', UNIT_PER_TYPE[self.product_id.price_base])],
                    limit=1
                ).id

    def _get_qty_to_invoice(self):
        self.ensure_one()

        if not self.display_type and self.product_id.price_base != 'normal':
            if self.product_id.price_base in ['weight', 'volume']:
                return self._get_qty_to_invoice_weight_or_volume()
            elif self.product_id.price_base == 'length':
                return self.qty_to_invoice, \
                       self.unit_length * self.qty_to_invoice
            elif self.product_id.price_base == 'width':
                return self.qty_to_invoice, \
                       self.unit_width * self.qty_to_invoice
            elif self.product_id.price_base == 'height':
                return self.qty_to_invoice, \
                       self.unit_height * self.qty_to_invoice

        return self.qty_to_invoice, self.qty_to_invoice

    def _get_qty_to_invoice_weight_or_volume(self):
        self.ensure_one()

        if self.qty_delivered_method == 'stock_move':
            outgoing_moves, incoming_moves = self._get_outgoing_incoming_moves()

            valid_moves = (outgoing_moves | incoming_moves).filtered(lambda m: m.state == 'done')

            time_line_moves = sorted(valid_moves, key=lambda x: x.picking_id and x.picking_id.date)
            qty_offset = self.qty_invoiced
            move_list = []
            for move in time_line_moves:
                qty = move.uom_id._compute_quantity(move.product_uom_qty, self.product_id.uom_id,
                                                         rounding_method='HALF-UP')
                if move.location_dest_id.usage == "customer":
                    if not move.origin_returned_move_id or (move.origin_returned_move_id and move.to_refund):
                        if qty_offset <= qty:
                            if qty - qty_offset >= 0.0:
                                move_list.append((qty - qty_offset, move))
                        qty_offset -= qty
                elif move.location_dest_id.usage != "customer" and move.to_refund:
                    qty_offset += qty

            qty_price = 0.0
            qty_to_add = self.qty_to_invoice

            for qty, move in move_list:
                full_move_qty = move.uom_id._compute_quantity(
                    move.product_uom_qty, self.product_id.uom_id,
                    rounding_method='HALF-UP'
                )
                if move.location_dest_id.usage == "customer":
                    if not move.origin_returned_move_id or (move.origin_returned_move_id and move.to_refund):
                        if qty_to_add > 0.0:
                            if move.product_id.price_base == 'weight':
                                qty_price += min(qty_to_add, qty) * (move.total_weight / full_move_qty)
                            elif move.product_id.price_base == 'volume':
                                qty_price += min(qty_to_add, qty) * (move.total_volume / full_move_qty)
                        qty_to_add -= qty
                elif move.location_dest_id.usage != "customer" and move.to_refund:
                    if move.product_id.price_base == 'weight':
                        qty_price -= qty * (move.total_weight / full_move_qty)
                    elif move.product_id.price_base == 'volume':
                        qty_price -= qty * (move.total_volume / full_move_qty)
                    qty_to_add += qty

            return max(qty_to_add, self.qty_to_invoice), qty_price
        else:
            return self.qty_to_invoice, self.qty_to_invoice

    # [20.0] `_get_price_total_and_subtotal_model` was removed from here. It is an
    # `account.move.line` method from Odoo 14 -- it never belonged on a sale order line,
    # so nothing ever called it -- and it computed taxes with `compute_all(...,
    # force_sign=...)`, an API the 20.0 tax engine no longer has. What it was reaching
    # for, taxing the physical quantity instead of the unit count, is what
    # `_prepare_base_line_for_taxes_computation` above does through the supported hook.
