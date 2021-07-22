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

FIELD_NAME_PER_TYPE = {
    'length': 'product_length',
    'width': 'product_width',
    'height': 'product_height',
    'surface': 'surface',
    'volume': 'volume',
    'weight': 'weight',
}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    so_weight = fields.Float('Weight', compute='_compute_weight_volume')
    so_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.depends('order_line')
    def _compute_weight_volume(self):
        for so in self:
            so.so_weight = 0.0
            so.so_volume = 0.0
            for line in so.order_line:
                so.so_weight += line.total_weight
                so.so_volume += line.total_volume


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface', related='product_id.surface', readonly=True)
    unit_weight = fields.Float(string='Unit Weight', related='product_id.weight', readonly=True)
    unit_volume = fields.Float(string='Unit Volume', related='product_id.volume', readonly=True)

    total_surface = fields.Float(string='Total Surface')
    total_weight = fields.Float(string='Total Weight')
    total_volume = fields.Float(string='Total Volume')

    price_qty = fields.Float(string='Price Qty')
    unit_price_uom_id = fields.Many2one('uom.uom', 'Price UoM')

    @api.onchange('product_id')
    def product_id_change(self):
        for sol in self:
            super(SaleOrderLine, sol).product_id_change()
            sol._compute_unit_price_uom()
            sol.compute_totals()

    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        for sol in self:
            product = sol.product_id
            if not product or product.price_base == 'normal':
                super(SaleOrderLine, sol).product_uom_change()
            sol._compute_unit_price_uom()
            sol.compute_totals()

    def _compute_unit_price_uom(self):
        uom_model = self.env['uom.uom']

        for sol in self:
            if sol.product_id:
                if sol.product_id.price_base == 'normal':
                    sol.unit_price_uom_id = sol.product_id.uom_id
                else:
                    sol.unit_price_uom_id = uom_model.search(
                        [('name', '=', UNIT_PER_TYPE[sol.product_id.price_base])],
                        limit=1
                    )
            else:
                sol.unit_price_uom_id = False

    @api.onchange('product_uom_qty', 'product_uom')
    @api.depends('product_uom_qty', 'product_uom')
    def compute_totals(self):
        for sol in self:
            normalized_qty = sol.product_uom._compute_quantity(sol.product_uom_qty, sol.product_id.uom_id) \
                if sol.product_uom else sol.product_uom_qty
            sol.total_surface = normalized_qty * sol.unit_surface
            sol.total_weight = normalized_qty * sol.unit_weight
            sol.total_volume = normalized_qty * sol.unit_volume

            sol.compute_price()

    @api.onchange('total_surface', 'total_weight', 'total_volume', 'product_uom_qty', 'product_uom')
    @api.depends('total_surface', 'total_weight', 'total_volume', 'product_uom_qty', 'product_uom')
    def compute_price(self):
        for sol in self:
            normalized_qty = sol.product_uom._compute_quantity(sol.product_uom_qty, sol.product_id.uom_id) \
                             if sol.product_uom else sol.product_uom_qty
            price_type = sol.product_id.price_base
            if price_type == 'length':
                price_qty = sol.unit_length * normalized_qty
            elif price_type == 'width':
                price_qty = sol.unit_width * normalized_qty
            elif price_type == 'height':
                price_qty = sol.unit_height * normalized_qty
            elif price_type == 'surface':
                price_qty = sol.total_surface
            elif price_type == 'weight':
                price_qty = sol.total_weight
            elif price_type == 'volume':
                price_qty = sol.total_volume
            else:
                price_qty = normalized_qty
            sol.price_qty = price_qty

            sol._compute_amount()

    @api.depends('price_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        for sol in self:
            price = sol.price_unit * (1 - (sol.discount or 0.0) / 100.0)
            taxes = sol.tax_id.compute_all(price, sol.order_id.currency_id, sol.price_qty,
                                           product=sol.product_id, partner=sol.order_id.partner_id)
            sol.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })

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

        return super()._prepare_invoice_line(**new_optional_values)

    def _get_price_uom_id(self):
        uom_model = self.env['uom.uom']

        self.ensure_one()

        if not self.display_type and self.product_id:
            if self.product_id.price_base == 'normal':
                return self.product_id.uom_id
            else:
                return uom_model.search(
                    [('name', '=', UNIT_PER_TYPE[self.product_id.price_base])],
                    limit=1
                )

    def _get_qty_to_invoice(self):
        self.ensure_one()

        if not self.display_type and self.product_id.price_base != 'normal':
            if self.product_id.price_base in ['weight', 'volume']:
                return self._get_qty_to_invoice_weight_or_volume()
            elif self.product_id.price_base == 'length':
                return self.unit_length * self.qty_to_invoice, \
                       self.unit_length * self.qty_to_invoice
            elif self.product_id.price_base == 'width':
                return self.unit_width * self.qty_to_invoice, \
                       self.unit_width * self.qty_to_invoice
            elif self.product_id.price_base == 'height':
                return self.unit_height * self.qty_to_invoice, \
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
                qty = move.product_uom._compute_quantity(move.product_uom_qty, self.product_id.uom_id,
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
                full_move_qty = move.product_uom._compute_quantity(
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

    @api.model
    def _get_price_total_and_subtotal_model(self, price_unit, quantity, discount,
                                            currency, product, partner, taxes, move_type):
        ''' This method is used to compute 'price_total' & 'price_subtotal'.

        :param price_unit:  The current price unit.
        :param quantity:    The current quantity.
        :param discount:    The current discount.
        :param currency:    The line's currency.
        :param product:     The line's product.
        :param partner:     The line's partner.
        :param taxes:       The applied taxes.
        :param move_type:   The type of the move.
        :return:            A dictionary containing 'price_subtotal' & 'price_total'.
        '''
        res = {}

        # Compute 'price_subtotal'.
        line_discount_price_unit = price_unit * (1 - (discount / 100.0))
        subtotal = self.price_qty * line_discount_price_unit

        # Compute 'price_total'.
        if taxes:
            force_sign = -1 if move_type in ('out_invoice', 'in_refund', 'out_receipt') else 1
            taxes_res = taxes._origin.with_context(force_sign=force_sign).compute_all(
                line_discount_price_unit,
                quantity=self.price_qty,
                currency=currency,
                product=product,
                partner=partner,
                is_refund=move_type in ('out_refund', 'in_refund'))
            res['price_subtotal'] = taxes_res['total_excluded']
            res['price_total'] = taxes_res['total_included']
        else:
            res['price_total'] = res['price_subtotal'] = subtotal

        # In case of multi currency, round before it's use for computing debit credit
        if currency:
            res = {k: currency.round(v) for k, v in res.items()}
        return res

