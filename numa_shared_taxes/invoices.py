#-*- coding: utf-8 -*-
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


from openerp.osv.osv import Model, except_osv
from openerp.tools.translate import _
import openerp.exceptions
from openerp import api

import datetime
import pdb
import pytz

class account_invoice_tax (Model):
    _inherit = "account.invoice.tax"

    @api.v7
    def compute(self, cr, uid, invoice_id, context=None):
        tax_obj = self.pool.get('account.tax')
        cur_obj = self.pool.get('res.currency')

        invoice = self.pool.get('account.invoice').browse(cr, uid, invoice_id, context=context)

        user_obj = self.pool.get('res.users')
        user = user_obj.browse(cr, uid, uid, context=context)
        saved_company = user.company_id
        user.write({'company_id': invoice.company_id.id})

        # Refresh invoice, with the company of the invoice
        invoice = self.pool.get('account.invoice').browse(cr, uid, invoice_id, context=context)

        company = invoice.journal_id.company_id
        total_wo_taxes = invoice.amount_untaxed
        partner = invoice.partner_id
        company_currency = company.currency_id.id
        
        today = datetime.date.today().strftime('%Y-%m-%d')

        tax_context = {
            'pool': self.pool,
            'uid': uid,
            'invoice': invoice,
            'date': invoice.date_invoice or today,
            'address': invoice.partner_id.commercial_partner_id.address_get(adr_pref='invoice'),
            'company': company,
            'datetime': datetime,
            'pdb': pdb,
            'pytz': pytz,
        }

        # Invoice line computation
        
        tax_grouped = {}
        for line in invoice.invoice_line:
            for tax in tax_obj.compute_all(cr, uid, 
                                            line.invoice_line_tax_id, 
                                            (line.price_unit* (1-(line.discount or 0.0)/100.0)), 
                                            line.quantity, 
                                            line.product_id, 
                                            invoice.partner_id,
                                            context=tax_context)['taxes']:
                val={}
                val['invoice_id'] = invoice.id
                val['name'] = tax['name']
                val['amount'] = tax['amount']
                val['manual'] = False
                val['sequence'] = tax['sequence']
                val['base'] = cur_obj.round(cr, uid, invoice.currency_id, tax['price_unit'] * line['quantity'])

                if invoice.type in ('out_invoice','in_invoice'):
                    val['base_code_id'] = tax['base_code_id']
                    val['tax_code_id'] = tax['tax_code_id']
                    val['base_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['base'] * tax['base_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['tax_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['amount'] * tax['tax_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['account_id'] = tax['account_collected_id'] or line.account_id.id
                    val['account_analytic_id'] = tax['account_analytic_collected_id']
                else:
                    val['base_code_id'] = tax['ref_base_code_id']
                    val['tax_code_id'] = tax['ref_tax_code_id']
                    val['base_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['base'] * tax['ref_base_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['tax_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['amount'] * tax['ref_tax_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['account_id'] = tax['account_paid_id'] or line.account_id.id
                    val['account_analytic_id'] = tax['account_analytic_paid_id']

                # If the taxes generate moves on the same financial account as the invoice line
                # and no default analytic account is defined at the tax level, propagate the
                # analytic account from the invoice line to the tax line. This is necessary
                # in situations were (part of) the taxes cannot be reclaimed,
                # to ensure the tax move is allocated to the proper analytic account.
                if not val.get('account_analytic_id') and line.account_analytic_id and val['account_id'] == line.account_id.id:
                    val['account_analytic_id'] = line.account_analytic_id.id

                key = (val['tax_code_id'], val['base_code_id'], val['account_id'], val['account_analytic_id'])
                if not key in tax_grouped:
                    tax_grouped[key] = val
                else:
                    tax_grouped[key]['amount'] += val['amount']
                    tax_grouped[key]['base'] += val['base']
                    tax_grouped[key]['base_amount'] += val['base_amount']
                    tax_grouped[key]['tax_amount'] += val['tax_amount']

        cstates = set()
        countries = set()
        
        if company.fiscal_country_state:
            cstates.add(company.fiscal_country_state)
        if company.fiscal_country:
            countries.add(company.fiscal_country)
        if invoice.partner_id.fiscal_country_state:
            cstates.add(invoice.partner_id.fiscal_country_state)
        if invoice.partner_id.fiscal_country:
            countries.add(invoice.partner_id.fiscal_country)

        if invoice.type in ['out_invoice', 'out_refund']:
            tax_list = company.sales_applicable_taxes

            for cstate in cstates:
                tax_list += cstate.sales_applicable_taxes
            for country in countries:
                tax_list += country.sales_applicable_taxes
        elif invoice.type in ['in_invoice', 'in_refund']:
            tax_list = company.purchase_applicable_taxes

            for cstate in cstates:
                tax_list += cstate.purchase_applicable_taxes
            for country in countries:
                tax_list += country.purchase_applicable_taxes
        else:
            tax_list = []
            
        # Invoice total taxes
        
        for tax in tax_list:
            if invoice.type in ('out_invoice','in_invoice'):
                if not tax.account_collected_id:
                    raise openerp.exceptions.Warning(_('Tax %s is not properly configured. No invoice account configured! Please check it') % tax.name)
            else:
                if not tax.account_paid_id:
                    raise openerp.exceptions.Warning(_('Tax %s is not properly configured. No payment account configured! Please check it') % tax.name)
                    
            for tax in tax_obj.compute_all(cr, uid, [tax], 
                                            total_wo_taxes, 
                                            1.00, 
                                            None,
                                            partner,
                                            context = tax_context)['taxes']:

                val={}
                val['invoice_id'] = invoice.id
                val['name'] = tax['name']
                val['amount'] = tax['amount']
                val['manual'] = False
                val['sequence'] = tax['sequence']
                val['base'] = total_wo_taxes

                if invoice.type in ('out_invoice','in_invoice'):
                    val['base_code_id'] = tax['base_code_id']
                    val['tax_code_id'] = tax['tax_code_id']
                    val['base_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['base'] * tax['base_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['tax_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['amount'] * tax['tax_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['account_id'] = tax['account_collected_id']
                    val['account_analytic_id'] = tax['account_analytic_collected_id']
                else:
                    val['base_code_id'] = tax['ref_base_code_id']
                    val['tax_code_id'] = tax['ref_tax_code_id']
                    val['base_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['base'] * tax['ref_base_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['tax_amount'] = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, val['amount'] * tax['ref_tax_sign'], context={'date': invoice.date_invoice or today}, round=False)
                    val['account_id'] = tax['account_paid_id']
                    val['account_analytic_id'] = tax['account_analytic_paid_id']

                key = (val['tax_code_id'], val['base_code_id'], val['account_id'], val['account_analytic_id'])
                if not key in tax_grouped:
                    tax_grouped[key] = val
                else:
                    tax_grouped[key]['amount'] += val['amount']
                    tax_grouped[key]['base'] += val['base']
                    tax_grouped[key]['base_amount'] += val['base_amount']
                    tax_grouped[key]['tax_amount'] += val['tax_amount']

        for t in tax_grouped.values():
            t['base'] = cur_obj.round(cr, uid, company.currency_id, t['base'])
            t['amount'] = cur_obj.round(cr, uid, company.currency_id, t['amount'])
            t['base_amount'] = cur_obj.round(cr, uid, company.currency_id, t['base_amount'])
            t['tax_amount'] = cur_obj.round(cr, uid, company.currency_id, t['tax_amount'])

        user.write({'company_id': saved_company.id})

        return tax_grouped

    @api.v8
    def compute(self, invoice):
        return self._model.compute(self._cr, self._uid, [invoice.id], context=self._context)

class account_invoice(Model):
    _inherit = "account.invoice"

    @api.v7
    def check_tax_lines(self, cr, uid, inv, compute_taxes, ait_obj):
        company_currency = self.pool['res.company'].browse(cr, uid, inv.company_id.id).currency_id
        if not inv.tax_line:
            for tax in compute_taxes.values():
                ait_obj.create(tax)
        else:
            tax_key = []
            for tax in inv.tax_line:
                if tax.manual:
                    continue
                key = (tax.tax_code_id.id, tax.base_code_id.id, tax.account_id.id, tax.account_analytic_id.id)
                tax_key.append(key)
                if not key in compute_taxes:
                    continue
                base = compute_taxes[key]['base']
                if abs(base - tax.base) > company_currency.rounding:
                    raise except_osv(_('Warning!'), _('Tax base different!\nClick on compute to update the tax base.'))
            for key in compute_taxes:
                if not key in tax_key:
                    raise except_osv(_('Warning!'), _('Taxes are missing!\nClick on compute button.'))

    @api.v8
    @api.multi
    def check_tax_lines(self, compute_taxes):
        return self._model.check_tax_lines(self._cr, self._uid, self, compute_taxes, self.env['account.invoice.tax'])
