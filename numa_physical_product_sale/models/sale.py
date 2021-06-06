from odoo import fields, models, api

import logging
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
