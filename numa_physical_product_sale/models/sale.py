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

    unit_price_uom_display = fields.Char(string='UP UoM', compute='_compute_unit_price_display')
    total_price_base = fields.Char(string='Base', compute='_compute_unit_price_display')

    @api.depends('product_uom_qty', 'product_uom', 'product_id')
    def _compute_unit_price_display(self):
        for sol in self:
            if not sol.product_id or sol.product_id.price_base == 'normal':
                sol.unit_price_uom_display = ''
                sol.total_price_base = ''
                continue

            product = sol.product_id.with_context(
                lang=sol.order_id.partner_id.lang,
                partner=sol.order_id.partner_id,
                quantity=sol.product_uom_qty,
                date=sol.order_id.date_order,
                pricelist=sol.order_id.pricelist_id.id,
                uom=sol.product_id.uom_id.id,
                fiscal_position=sol.env.context.get('fiscal_position')
            )

            normalized_qty = sol.product_uom._compute_quantity(sol.product_uom_qty, product.uom_id) \
                             if sol.product_uom else sol.product_uom_qty
            normalized_base = normalized_qty * product[FIELD_NAME_PER_TYPE[product.price_base]]

            sol.unit_price_uom_display = 'x %s' % (UNIT_PER_TYPE[product.price_base])
            sol.total_price_base = '%f %s' % (
                normalized_base,
                UNIT_PER_TYPE[product.price_base]
            )

            no_variant_attributes_price_extra = [
                ptav.price_extra for ptav in sol.product_no_variant_attribute_value_ids.filtered(
                    lambda ptav:
                    ptav.price_extra and
                    ptav not in product.product_template_attribute_value_ids
                )
            ]
            if no_variant_attributes_price_extra:
                product = product.with_context(
                    no_variant_attributes_price_extra=tuple(no_variant_attributes_price_extra)
                )

            product_context = dict(self.env.context, partner_id=sol.order_id.partner_id.id,
                                   uom=sol.product_id.uom_id.id,
                                   date=sol.order_id.date_order)

            final_price, rule_id = sol.order_id.pricelist_id.with_context(product_context).get_product_price_rule(
                product or sol.product_id, sol.product_uom_qty or 1.0, sol.order_id.partner_id)

            sol.price_unit = final_price

            sol._compute_amount()

    @api.onchange('product_id', 'price_unit', 'product_uom', 'product_uom_qty', 'tax_id')
    def _onchange_discount(self):
        if not (self.product_id and self.product_uom and
                self.order_id.partner_id and self.order_id.pricelist_id and
                self.order_id.pricelist_id.discount_policy == 'without_discount' and
                self.env.user.has_group('product.group_discount_per_so_line')):
            return

        self.discount = 0.0
        product = self.product_id.with_context(
            lang=self.order_id.partner_id.lang,
            partner=self.order_id.partner_id,
            quantity=self.product_uom_qty,
            date=self.order_id.date_order,
            pricelist=self.order_id.pricelist_id.id,
            uom=self.product_uom.id,
            fiscal_position=self.env.context.get('fiscal_position')
        )

        product_context = dict(self.env.context, partner_id=self.order_id.partner_id.id, date=self.order_id.date_order, uom=self.product_uom.id)

        self._compute_unit_price_display()
        new_list_price, currency = self.with_context(product_context)._get_real_price_currency(product, rule_id, self.product_uom_qty, self.product_uom, self.order_id.pricelist_id.id)

        if new_list_price != 0:
            if self.order_id.pricelist_id.currency_id != currency:
                # we need new_list_price in the same currency as price, which is in the SO's pricelist's currency
                new_list_price = currency._convert(
                    new_list_price, self.order_id.pricelist_id.currency_id,
                    self.order_id.company_id or self.env.company, self.order_id.date_order or fields.Date.today())
            discount = (new_list_price - price) / new_list_price * 100
            if (discount > 0 and new_list_price > 0) or (discount < 0 and new_list_price < 0):
                self.discount = discount

    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        self.ensure_one()
        for sol in self:
            product = sol.product_id
            if not product or product.price_base == 'normal':
                return super(SaleOrderLine, sol).product_uom_change()
            else:
                sol._compute_unit_price_display()

    @api.onchange('product_id')
    def product_id_change(self):
        self.ensure_one()
        for sol in self:
            super(SaleOrderLine, sol).product_id_change()

            product = sol.product_id
            if product and product.price_base != 'normal':
                sol._compute_unit_price_display()

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        """
        Compute the amounts of the SO line.
        """
        super(SaleOrderLine, self)._compute_amount()

        # Correct values
        for line in self:
            if not line.product_id or line.product_id.price_base == 'normal':
                continue

            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)

            normalized_qty = line.product_uom._compute_quantity(line.product_uom_qty, line.product_id.uom_id) \
                             if line.product_uom else line.product_uom_qty
            normalized_base = normalized_qty * line.product_id[FIELD_NAME_PER_TYPE[line.product_id.price_base]]

            taxes = line.tax_id.compute_all(price, line.order_id.currency_id, normalized_base,
                                            product=line.product_id, partner=line.order_id.partner_shipping_id)
            line.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })
