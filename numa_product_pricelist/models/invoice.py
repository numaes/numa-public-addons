# -*- coding: utf-8 -*-

from odoo import fields, models, api, exceptions
from odoo.tools.translate import _
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo.tools import safe_eval

import logging


class numa_account_invoice(models.Model):
    _inherit = 'account.invoice'

    amount_discounts = fields.Monetary(string=u'Descuentos', store=True, readonly=True, compute='_compute_amount',
                                       track_visibility='always')
    amount_untaxed_nodiscounts = fields.Monetary(string=u'Subtotal sin descuentos', store=True, readonly=True,
                                                 compute='_compute_amount')
    amount_with_discounts = fields.Monetary(string=u'Total', store=True, readonly=True, compute='_compute_amount')
    discount_ids = fields.One2many('numa.account.invoice.discount', 'invoice_id', string=u'Descuentos', readonly=True,
                                   states={'draft': [('readonly', False)]}, copy=False)

    @api.one
    @api.depends('invoice_line_ids.price_subtotal', 'tax_line_ids.amount', 'currency_id', 'company_id', 'date_invoice',
                 'type', 'discount_ids','perception_ids')
    def _compute_amount(self):
        super(numa_account_invoice, self)._compute_amount()

        self.amount_untaxed_nodiscounts = self.amount_untaxed
        self.amount_discounts = sum(discount.amount for discount in self.discount_ids)
        self.amount_untaxed = self.amount_untaxed_nodiscounts - self.amount_discounts
        self.amount_total = self.amount_untaxed + self.amount_tax
        amount_total_company_signed = self.amount_total
        amount_untaxed_signed = self.amount_untaxed

        if self.currency_id and self.company_id and self.currency_id != self.company_id.currency_id:
            currency_id = self.currency_id.with_context(date=self.date_invoice)
            amount_total_company_signed = currency_id.compute(self.amount_total, self.company_id.currency_id)
            amount_untaxed_signed = currency_id.compute(self.amount_untaxed, self.company_id.currency_id)
        sign = self.type in ['in_refund', 'out_refund'] and -1 or 1
        self.amount_total_company_signed = amount_total_company_signed * sign
        self.amount_total_signed = self.amount_total * sign
        self.amount_untaxed_signed = amount_untaxed_signed * sign
        #perception_grouped = self.get_perception_values()
        #perception_lines = self.perception_ids.filtered('manual')
        #perception_total = 0.0
        #for perception in perception_grouped.values():
            #perception_lines += perception_lines.new(perception)
            #perception_total += perception['amount']
        #self.perception_ids = perception_lines
        #self.amount_perceptions = perception_total
        #self.amount_total = self.amount_untaxed + self.amount_tax #+ self.amount_perceptions
# self.amount_with_discounts = self.amount_total + self.amount_discounts  #habria que cambiar amount_total

    @api.onchange('invoice_line_ids','pricelist_id')
    def _onchange_invoice_discount_ids(self):
        discount_lines = self.discount_ids.filtered('manual')
        discount_lines_pricelist = {}
        discount_total = 0.0
        if self.pricelist_id:
            lines = []
            for line in self.invoice_line_ids:
                lines.append({
                    'product_id': line.product_id,
                    'quantity': line.quantity,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'tax_ids': line.invoice_line_tax_ids,
                    'subtotal': line.price_subtotal,
                    'lot_id': line.product_lot_id,
                    'serial_id': line.product_serial_id,
                })

            if self.type in ['out_invoice', 'out_refund']:
                discount_lines_pricelist = self.pricelist_id.compute_discounts(
                    sale_order_id = False,
                    invoice_id = self.id,
                    issuer_id=self.company_id.partner_id,
                    sales_point_id=self.afip_sales_point,
                    partner_id=self.commercial_partner_id,
                    destination_address=self.commercial_partner_id,
                    lines=lines,
                    outputDiscounts=[],
                )
            else:
                discount_lines_pricelist = self.pricelist_id.compute_discounts(
                    issuer_id=self.commercial_partner_id,
                    sales_point_id=None,
                    partner_id=self.company_id.partner_id,
                    destination_address=self.company_id.partner_id,
                    lines=lines,
                )

            for discount in discount_lines_pricelist:
                discount_lines += discount_lines.new(discount)
                discount_total += discount['amount']
        self.discount_ids = discount_lines
        self.amount_discounts = discount_total
        self._compute_amount()
        return

    @api.multi
    def get_taxes_values(self):
        self._onchange_invoice_discount_ids()
        result = super(numa_account_invoice, self).get_taxes_values()
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
        # loop the invoice.perception_ids in reversal sequence
        for discount in self.discount_ids:
            res.append({
                'name': discount.display_discount_name,
                'price_unit': discount.amount,
                'quantity': 1,
                'price': -discount.amount if self.type in ['out_invoice','in_refund'] else discount.amount,
                'account_id': discount.account_id.id,
                'invoice_id': self.id,
            })
        return res

    @api.model
    def tax_line_move_line_get(self):
        res = super(numa_account_invoice, self).tax_line_move_line_get()
        res += self.discount_move_line_get()
        return res


class numa_account_invoice_discount(models.Model):
    _name = 'numa.account.invoice.discount'

    invoice_id = fields.Many2one('account.invoice', string='Invoice', ondelete='cascade')
    display_discount_name = fields.Char(u'Descuento')
    base = fields.Monetary(string=u'Base Cálculo')
    amount = fields.Monetary(string=u'Monto')
    currency_id = fields.Many2one('res.currency', string=u'Moneda', store=True, readonly=True,
                                  related='invoice_id.currency_id')
    account_id = fields.Many2one('account.account', string=u'Cuenta Percepción', required=True)
    manual = fields.Boolean(default=True, readonly=True)
    type_discount = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase')], string='Type', readonly=True)

    date = fields.Date(string='Partner', related='invoice_id.date_invoice', store=True, readonly=True)
    partner = fields.Char('Partner', related='invoice_id.partner_id.name', store=True, readonly=True)
    company = fields.Char('Company', related='invoice_id.company_id.name', store=True, readonly=True)
    percent = fields.Float('Porcentaje')


    product_tmpl_id = fields.Many2one('product.template', string='Plantilla Producto', ondelete='restrict')
    product_id = fields.Many2one('product.product', string='Variante Producto', ondelete='restrict')
    product_categ_id = fields.Many2one('product.category', string=u'Categoría', ondelete='restrict')
    product_trademark_id = fields.Many2one('product.trademark', string='Marca', ondelete='restrict')
    product_attr_value_id = fields.Many2one('product.attribute.value', string='Valor AtributoPlantilla Producto', ondelete='restrict')
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

