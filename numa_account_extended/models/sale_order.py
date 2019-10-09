# -*- coding: utf-8 -*-

from odoo import fields, models, api, exceptions, _

import logging
_logger = logging.getLogger(__name__)

class AccountSaleOrder(models.Model):
    _inherit = 'sale.order'

    image = fields.Binary(string='Image', related='company_id.logo', store=True, readonly=True)
    base_sale_order = fields.Many2one('sale.order','Base Sale Order')
    partner_name = fields.Char('Partner name')
    partner_vat = fields.Char('Partner VAT')
    invoice_address_street = fields.Char('Invoice address street')
    invoice_address_street2 = fields.Char('Invoice address street2')
    invoice_address_zip = fields.Char('Invoice address zip')
    invoice_address_city = fields.Char('Invoice address city')
    invoice_address_fed_state = fields.Char('Invoice address fed_state')
    invoice_address_country = fields.Char('Invoice address country')

    delivery_address_street = fields.Char('Invoice address street')
    delivery_address_street2 = fields.Char('Invoice address street2')
    delivery_address_zip = fields.Char('Invoice address zip')
    delivery_address_city = fields.Char('Invoice address city')
    delivery_address_fed_state = fields.Char('Invoice address fed_state')
    delivery_address_country = fields.Char('Invoice address country')

    legal_country_code = fields.Char('Pais Legal', related='company_id.partner_id.country_id.code')

    #pricelist_id = fields.Many2one('product.pricelist', 'Pricelist', on_delete='restrict')
    notes = fields.Text('Notes')

    tax_line_ids = fields.One2many('account.sale.order.tax', 'sale_order_id', string='Tax Lines',
        readonly=True, states={'draft': [('readonly', False)]}, copy=True)

    @api.onchange('order_line')
    def _onchange_order_line(self):
        taxes_grouped = self.get_taxes_values()
        tax_lines = self.tax_line_ids.filtered('manual')
        for tax in taxes_grouped.values():
            tax_lines += tax_lines.new(tax)
        self.tax_line_ids = tax_lines
        return

    @api.onchange('partner_id')
    def on_partner_changed(self):
        sale_order = self
        if sale_order.partner_id:
            if sale_order.partner_id.property_product_pricelist:
                sale_order.pricelist_id = sale_order.partner_id.property_product_pricelist.id

    def _prepare_tax_line_vals(self, line, tax):
        """ Prepare values to create an account.sale.order.tax line

        The line parameter is an account.sale.order.line, and the
        tax parameter is the output of account.tax.compute_all().
        """
        vals = {
            'sale_order_id': self.id,
            'name': tax['name'],
            'tax_id': tax['id'],
            'amount': tax['amount'],
            'base': tax['base'],
            'manual': False,
            'sequence': tax['sequence'],
            'account_analytic_id': tax['analytic'] or False,
            'account_id': tax['account_id'],
        }

        # If the taxes generate moves on the same financial account as the invoice line,
        # propagate the analytic account from the invoice line to the tax line.
        # This is necessary in situations were (part of) the taxes cannot be reclaimed,
        # to ensure the tax move is allocated to the proper analytic account.
        #if not vals.get('account_analytic_id') and line.account_analytic_id and vals['account_id'] == line.account_id.id:
            #vals['account_analytic_id'] = line.account_analytic_id.id

        return vals

    @api.multi
    def copy(self,default_values=None):
        context = self.env.context or {}
        new_values = dict(default_values) if default_values else {}
        new_values['base_sale_order'] = self.id
        return super(AccountSaleOrder,self).copy(new_values)


    @api.multi
    def get_taxes_values(self):
        #self._onchange_sale_order_discount_ids()
        tax_grouped = {}
        for line in self.order_line:
            price_unit = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price_unit, self.currency_id, line.product_uom_qty, line.product_id, self.partner_id)['taxes']
            for tax in taxes:
                val = self._prepare_tax_line_vals(line, tax)
                key = self.env['account.sale.order.tax'].browse(tax['id']).get_grouping_key(val)

                if key not in tax_grouped:
                    tax_grouped[key] = val
                else:
                    tax_grouped[key]['amount'] += val['amount']
                    tax_grouped[key]['base'] += val['base']

        return tax_grouped

class AccountSaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    bien_de_uso = fields.Boolean(u'Bien Uso')

class AccountSaleOrderTax(models.Model):
    _name = "account.sale.order.tax"
    _description = "Sale Order Tax"
    _order = 'sequence'

    def _compute_base_amount(self):
        tax_grouped = {}
        for sale_order in self.mapped('sale_order_id'):
            tax_grouped[sale_order.id] = sale_order.get_taxes_values()
        for tax in self:
            tax.base = 0.0
            if tax.tax_id:
                key = tax.tax_id.get_grouping_key({
                    'tax_id': tax.tax_id.id,
                    'account_id': tax.account_id.id,
                    'account_analytic_id': tax.account_analytic_id.id,
                })
                if tax.sale_order_id and key in tax_grouped[tax.sale_order_id.id]:
                    tax.base = tax_grouped[tax.sale_order_id.id][key]['base']
                else:
                    _logger.warning('Tax Base Amount not computable probably due to a change in an underlying tax (%s).', tax.tax_id.name)

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', ondelete='cascade', index=True)
    name = fields.Char(string='Tax Description', required=True)
    tax_id = fields.Many2one('account.tax', string='Tax', ondelete='restrict')
    account_id = fields.Many2one('account.account', string='Tax Account', domain=[('deprecated', '=', False)])
    account_analytic_id = fields.Many2one('account.analytic.account', string='Analytic account')
    amount = fields.Monetary()
    manual = fields.Boolean(default=True)
    sequence = fields.Integer(help="Gives the sequence order when displaying a list of invoice tax.")
    company_id = fields.Many2one('res.company', string='Company', related='sale_order_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one('res.currency', related='sale_order_id.currency_id', store=True, readonly=True)
    base = fields.Monetary(string='Base', compute='_compute_base_amount')

    # DO NOT FORWARD-PORT!!! ONLY FOR v10
    @api.model
    def create(self, vals):
        inv_tax = super(AccountSaleOrderTax, self).create(vals)
        # Workaround to make sure the tax amount is rounded to the currency precision since the ORM
        # won't round it automatically at creation.
        if inv_tax.company_id.tax_calculation_rounding_method == 'round_globally':
            inv_tax.amount = inv_tax.currency_id.round(inv_tax.amount)
        return inv_tax

    def get_grouping_key(self, sale_order_tax_val):
        """ Returns a string that will be used to group account.invoice.tax sharing the same properties"""
        self.ensure_one()
        return str(sale_order_tax_val['tax_id']) + '-' + str(sale_order_tax_val['account_id']) + '-' + str(sale_order_tax_val['account_analytic_id'])