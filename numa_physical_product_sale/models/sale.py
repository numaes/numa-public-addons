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
                so.so_weight += line.product_uom_qty * line.product_id.weight
                so.so_volume += line.product_uom_qty * line.product_id.volume


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    product_width_rel = fields.Float(string='Width', related='product_id.product_width', readonly=True)
    product_length_rel = fields.Float(string='Length', related='product_id.product_length', readonly=True)
    product_height_rel = fields.Float(string='Height', related='product_id.product_height', readonly=True)
    product_surface_rel = fields.Float(string='Surface', related='product_id.surface', readonly=True)
    product_weight_rel = fields.Float(string='Weight', related='product_id.weight', readonly=True)
    product_volume_rel = fields.Float(string='Volume', related='product_id.volume', readonly=True)

    unit_price_display = fields.Char(string='Unit price', compute='_compute_unit_price_display')

    def _compute_unit_price_display(self):
        for sol in self:
            product = sol.product_id
            if not product:
                continue

            sol.unit_price_display = ('%%.%df %s/%s' % (
                sol.order_id.currency_id.decimal_places,
                sol.order_id.currency_id.symbol,
                product.uom_id.name if product and product.type in ('product', 'consu') else
                UNIT_PER_TYPE[product.price_base]) %
                sol.price_unit)

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        """
        Compute the amounts of the SO line.
        """
        super(SaleOrderLine, self)._compute_amount()

        # Correct values
        for line in self:
            if not line.product_id:
                line.price_tax = 0.0
                line.price_total = 0.0
                line.price_subtotal = 0.0
                continue

            if line.product_id.type in ('product', 'consu') and line.product_id.price_base != 'normal':
                unit_price = line.product_id[FIELD_NAME_PER_TYPE[line.product_id.price_base]] * line.price_unit
            else:
                unit_price = line.price_unit
            price = unit_price * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price, line.order_id.currency_id, line.product_uom_qty,
                                            product=line.product_id, partner=line.order_id.partner_shipping_id)
            line.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })
