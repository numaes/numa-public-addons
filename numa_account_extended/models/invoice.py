# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2013
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


from odoo import fields, models, api, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    image = fields.Binary(string='Image', related='company_id.logo', store=True, readonly=True)
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

    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist', on_delete='restrict')
    notes = fields.Text('Notes')


    @api.onchange('pricelist_id', 'fiscal_position_id')
    def recompute_invoice(self):
        invoice = self
        if invoice.pricelist_id:
            invoice.currency_id = invoice.pricelist_id.currency_id.id
            for line in invoice.invoice_line_ids:
                if line.product_id:
                    line._onchange_product_id()

    @api.onchange('partner_id')
    def on_partner_changed(self):
        invoice = self
        if invoice.partner_id:
            if invoice.type in ['out_invoice', 'out_refund']:
                if invoice.partner_id.property_product_pricelist:
                    invoice.pricelist_id = invoice.partner_id.property_product_pricelist.id
            else:
                if invoice.partner_id.property_supplier_product_pricelist:
                    invoice.pricelist_id = invoice.partner_id.property_supplier_product_pricelist.id

    @api.multi
    def action_invoice_open(self):
        fiscal_period_object = self.env['account.period']
        for invoice in self:
            fiscal_period = fiscal_period_object.search([('state', '=', 'open'),
                                                         ('fiscalyear_id.state', '=', 'open'),
                                                         ('company_id', '=', invoice.company_id.id),
                                                         ('date_start', '<=', invoice.date_invoice),
                                                         ('date_end', '>=', invoice.date_invoice),
                                                         ('special', '=', False), ])
            if not fiscal_period:
                raise UserError(_('Fiscal Year or Fiscal Period not Open for the Date: %s') % invoice.date_invoice)

            super_ret = super(AccountInvoice, invoice).action_invoice_open()

        return

class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    bien_de_uso = fields.Boolean(u'Bien Uso')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        res = super(AccountInvoiceLine, self)._onchange_product_id()

        if self.product_id and self.invoice_id.pricelist_id:
            self.price_unit, _ = self.invoice_id.pricelist_id.get_product_price_rule(
                self.product_id, self.quantity or 1.0, self.invoice_id.partner_id)

        return res
