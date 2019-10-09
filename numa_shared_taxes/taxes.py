#-*- coding: utf-8 -*-
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
from odoo.exceptions import UserError, ValidationError

import logging
_logger = logging.getLogger(__name__)

class AccountTax(models.Model):
    _inherit = 'account.tax'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=False,
        default=False)

    account_id = fields.Many2one(
        'account.account',
        domain=[('deprecated', '=', False)],
        string='Tax Account',
        ondelete='restrict',
        help="Account that will be set on invoice tax lines for invoices. Leave empty to use the expense account.", oldname='account_collected_id')

class ResCountry(models.Model):
    _inherit = "res.country"

    sales_taxes = fields.Many2many(
        'account.tax'
        'country_sales_taxes', 'country_id', 'tax_id',
        'Country wide sales taxes',
        domain="[('company_id','=',False)]",
        help="Taxes applicable on sales, for all companies operating in the country")

    payment_taxes = fields.Many2many(
        'account.tax'
        'country_payment_taxes', 'country_id', 'tax_id',
        'Country wide payment taxes',
        domain="[('company_id','=',False)]",
        help="Taxes applicable on payments, for all companies operating in the country")

class ResCountryState(models.Model):
    _inherit = "res.country.state"

    sales_taxes = fields.Many2many(
        'account.tax'
        'country_sales_taxes', 'country_id', 'tax_id',
        'Country state wide sales taxes',
        domain="[('company_id','=',False)]",
        help="Taxes applicable on sales, for all companies operating in this country state")

    payment_taxes = fields.Many2many(
        'account.tax'
        'country_payment_taxes', 'country_id', 'tax_id',
        'Country state wide payment taxes',
        domain="[('company_id','=',False)]",
        help="Taxes applicable on payments, for all companies operating in this country state")

class ResCompany(models.Model):
    _inherit = "res.company"

    fiscal_country_state = fields.Many2one('res.country.state', 'Fiscal country state',
                                           related=['partner_id', 'fiscal_country_state'],
                                           help="Country state to be used for fiscal issues")

    fiscal_country = fields.Many2one('res.country', 'Fiscal country',
                                      related=['partner_id', 'fiscal_country'],
                                      help="Country to be used for fiscal issues")
    sales_taxes = fields.Many2many(
        'account.tax'
        'country_sales_taxes', 'country_id', 'tax_id',
        'Company specific sales taxes',
        domain="[('company_id','=',False)]",
        help="Taxes applicable on sales, for this particular company")

    payment_taxes = fields.Many2many(
        'account.tax'
        'country_payment_taxes', 'country_id', 'tax_id',
        'Company specific payment taxes',
        domain="[('company_id','=',False)]",
        help="Taxes applicable on payments, for this particular company")

    @api.onchange('fiscal_country_state')
    @api.depends('fiscal_country_state')
    @api.multi
    def onchange_fiscal_country_state(self):
        if self.fiscal_country_state:
            self.fiscal_country = self.fiscal_country_state.country_id
        return False

    @api.onchange('fiscal_country')
    @api.depends('fiscal_country')
    @api.multi
    def onchange_fiscal_country(self):
        if self.fiscal_country_state and self.fiscal_country_state.country_id != self:
            self.fiscal_country_state = False
        return False

class ResPartner(models.Model):
    _inherit = "res.partner"

    fiscal_country_state = fields.Many2one('res.country.state', 'Fiscal country state',
                                           help="Country state to be used for fiscal issues")

    fiscal_country = fields.Many2one('res.country', 'Fiscal country',
                                      help="Country to be used for fiscal issues")

    @api.onchange('fiscal_country_state')
    @api.depends('fiscal_country_state')
    @api.multi
    def onchange_fiscal_country_state(self):
        if self.fiscal_country_state:
            self.fiscal_country = self.fiscal_country_state.country_id
        return False

    @api.onchange('fiscal_country')
    @api.depends('fiscal_country')
    @api.multi
    def onchange_fiscal_country(self):
        if self.fiscal_country_state and self.fiscal_country_state.country_id != self:
            self.fiscal_country_state = False
        return False

