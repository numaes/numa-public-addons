# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2017
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import models, fields, api, _
from odoo import exceptions
import odoo.addons.decimal_precision as dp
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

import logging
_logger = logging.getLogger(__name__)

class numa_purchase_order(models.Model):
    _inherit = 'purchase.order'

    #pricelist_id = fields.Many2one(domain=[('for_sale', '=', True)])
    amount_discounts = fields.Monetary(string=u'Descuentos', store=True, readonly=True, compute='_amount_all', track_visibility='always')
    amount_untaxed_nodiscounts = fields.Monetary(string=u'Subtotal sin descuentos', store=True, readonly=True, compute='_amount_all')
    amount_with_discounts = fields.Monetary(string=u'Total', store=True, readonly=True, compute='_amount_all')
    discount_ids = fields.One2many('numa.purchase.order.discount', 'purchase_order_id', string=u'Descuentos', readonly=True,
                                   states={'draft': [('readonly', False)]}, copy=False)
    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist', ondelete='restrict')

    @api.one
    @api.depends('order_line.price_subtotal', 'tax_line_ids.amount', 'currency_id', 'company_id', 'discount_ids')
    #@api.depends('order_line.price_subtotal', 'tax_line_ids.amount', 'currency_id', 'company_id', 'date_invoice','type', 'discount_ids')
    def _amount_all(self):
        super(numa_purchase_order, self)._amount_all()

        self.amount_untaxed_nodiscounts = self.amount_untaxed
        self.amount_discounts = sum(discount.amount for discount in self.discount_ids)
        self.amount_untaxed = self.amount_untaxed_nodiscounts - self.amount_discounts
        perception_grouped = self.get_perception_values()
        perception_lines = self.perception_ids.filtered('manual')
        perception_total = 0.0
        for perception in perception_grouped.values():
            perception_lines += perception_lines.new(perception)
            perception_total += perception['amount']
        self.perception_ids = perception_lines
        self.amount_perceptions = perception_total
        self.amount_tax = sum(tax.amount for tax in self.tax_line_ids)
        self.amount_total = self.amount_untaxed + self.amount_tax + self.amount_perceptions
# self.amount_with_discounts = self.amount_total + self.amount_discounts  #habria que cambiar amount_total

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.pricelist_id = self.partner_id.supplier_pricelist_id
            domain = {'pricelist_id': [('id', 'in', self.partner_id.profile_pricelist_customer_id.ids)]}
        else:
            self.pricelist_id = False
            domain = {'pricelist_id': [('id', '=', 0)]}

        return {'domain': domain}

    @api.onchange('order_line','pricelist_id')
    def _onchange_purchase_order_discount_ids(self):
        discount_lines = self.discount_ids.filtered('manual')
        discount_total = 0.0
        if self.pricelist_id:
            lines = []
            for line in self.order_line:
                lines.append({
                    'product_id': line.product_id,
                    'product_uom_qty': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'tax_ids': line.tax_id,
                    'subtotal': line.price_subtotal,
                    'lot_id': line.product_lot_id,
                    'serial_id': line.product_serial_id,
                })

            discount_lines_pricelist = self.pricelist_id.compute_discounts(purchase_order_id = self.id,
                                                                           invoice_id = False,
                                                                           issuer_id=self.company_id.partner_id,
                                                                           sales_point_id=None,
                                                                           partner_id=None,
                                                                           destination_address=None,
                                                                           lines=lines,
                                                                           outputDiscounts=[])

            if discount_lines_pricelist:
                for discount in discount_lines_pricelist:
                    discount_lines += discount_lines.new(discount)
                    discount_total += discount['amount']

        self.discount_ids = discount_lines
        self.amount_discounts = discount_total
        self._amount_all()
        return

    @api.multi
    def get_taxes_values(self):
        self._onchange_purchase_order_discount_ids()
        result = super(numa_purchase_order, self).get_taxes_values()
        for discount in self.discount_ids:
            found = False
            for key, data in result.items():
                if data['tax_id'] == discount.tax_id.id:
                    data['base'] -= discount.amount
                    data['amount'] -= discount.amount_tax
                    if data['amount'] < 0:
                        raise exceptions.Warning(
                            _(u'El descuento %s sobre el impuesto %s en la factura ha convertido al impuesto en negativo! Es inválido') % \
                             (discount.display_discount_name,discount.tax_id.name))
                    found = True
                    break
            if not found:
                raise exceptions.Warning(_(u'No se encontró el impuesto %s en la factura, aplicado en el descuento %s! Es inválido') % \
                                  (discount.tax_id.name, discount.display_discount_name))
        return result

    @api.model
    def discount_move_line_get(self):
        res = []
        # loop the sale order.perception_ids in reversal sequence
        for discount in self.discount_ids:
            res.append({
                'name': discount.display_discount_name,
                'price_unit': discount.amount,
                'quantity': 1,
                'price': -discount.amount,
                'account_id': discount.account_id.id,
                'purchase_order_id': self.id,
            })
        return res

    @api.model
    def tax_line_move_line_get(self):
        res = super(numa_purchase_order, self).tax_line_move_line_get()
        res += self.discount_move_line_get()
        return res


class numa_purchase_order_discount(models.Model):
    _name = 'numa.purchase.order.discount'

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', ondelete='cascade')
    display_discount_name = fields.Char(u'Descuento')
    base = fields.Monetary(string=u'Base Cálculo')
    amount = fields.Monetary(string=u'Monto')
    currency_id = fields.Many2one('res.currency', string=u'Moneda', store=True, readonly=True, related='purchase_order_id.currency_id')
    account_id = fields.Many2one('account.account', string=u'Cuenta Percepción', required=True)
    manual = fields.Boolean(default=True, readonly=True)
    #type_discount = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase')], string='Type', readonly=True)

    date = fields.Date(string='Partner', related='purchase_order_id.date_approve', store=True, readonly=True)
    partner = fields.Char('Partner', related='purchase_order_id.partner_id.name', store=True, readonly=True)
    company = fields.Char('Company', related='purchase_order_id.company_id.name', store=True, readonly=True)
    percent = fields.Float('Porcentaje')


    product_tmpl_id = fields.Many2one('product.template', string='Plantilla Producto', ondelete='restrict')
    product_id = fields.Many2one('product.product', string='Variante Producto', ondelete='restrict')
    product_categ_id = fields.Many2one('product.category', string=u'Categoría', ondelete='restrict')
    product_trademark_id = fields.Many2one('product.trademark', string='Marca', ondelete='restrict')
    product_attr_value_id = fields.Many2one('product.attribute.value', string='Valor Atributo Plantilla Producto', ondelete='restrict')
    product_lot_id = fields.Many2one('stock.production.lot', string='Lote', ondelete='restrict')
    product_serial_id = fields.Many2one('product.serial_number', string='Serial', ondelete='restrict')
    tax_id = fields.Many2one('account.tax', string='Impuesto', ondelete='restrict')
    amount_tax = fields.Monetary(string=u'Impuesto')

    @api.onchange('base','percent')
    def onchange_base(self):
        self.amount = self.base * self.percent / 100.0

    @api.onchange('amount','product_tax_id')
    def onchange_amount(self):
        if self.tax_id:
            self.amount_tax = self.tax_id._compute_amount(self.base, self.amount, quantity=1.0, product=None, partner=None)

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.multi
    @api.onchange('product_id')
    def product_change(self):
        if self.order_id.pricelist_id and self.order_id.partner_id:
            for line in self:
                pricelist = line.order_id.pricelist_id.with_context(
                    lot_id=line.product_lot_id or False,
                    serial_id=line.product_serial_id or False,
                    afip_punto_venta_id=False,
                    salesman_id=line.order_id.user_id.id,
                    city_id=line.order_id.partner_invoice_id.street_id.city_id.id,
                    country_state_id=line.order_id.partner_invoice_id.state_id.id,
                    country_id=line.order_id.partner_invoice_id.country_id.id,
                )
                line.price_unit = pricelist._compute_price_rule(
                    [(line.product_id, line.product_uom_qty, line.order_id.partner_id)],
                    line.order_id.date_order,
                    line.product_uom.id if line.product_uom else False,
                )[line.product_id.id][0]

        return False

    @api.onchange('product_qty', 'product_uom')
    def _onchange_quantity(self):
        if not self.product_id:
            return

        seller = self.product_id._select_seller(
            partner_id=self.partner_id,
            quantity=self.product_qty,
            date=self.order_id.date_order and self.order_id.date_order[:10],
            uom_id=self.product_uom)

        if seller or not self.date_planned:
            self.date_planned = self._get_date_planned(seller).strftime(DEFAULT_SERVER_DATETIME_FORMAT)

        if not seller or not self.partner_id.supplier_pricelist_id:
            return

        sellerPrice = self.partner_id.supplier_pricelist_id.get_product_price(
            self.product_id,
            self.product_qty,
            self.partner_id,
            date=self.order_id.date_order and self.order_id.date_order[:10],
            uom_id=self.product_uom
        )

        price_unit = self.env['account.tax']._fix_tax_included_price_company(sellerPrice,
                                                                             self.product_id.supplier_taxes_id,
                                                                             self.taxes_id,
                                                                             self.company_id) if seller else 0.0

        if price_unit and seller and self.order_id.currency_id and seller.currency_id != self.order_id.currency_id:
            price_unit = seller.currency_id.compute(price_unit, self.order_id.currency_id)

        if seller and self.product_uom and seller.product_uom != self.product_uom:
            price_unit = seller.product_uom._compute_price(price_unit, self.product_uom)

        self.price_unit = price_unit

