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


from odoo import fields, models, api
from odoo.tools.translate import _
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta

import logging


class numa_account_retencion(models.Model):
    _name = 'numa.account_retencion'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    company_id = fields.Many2one('res.company', string='Company', change_default=True, required=True, readonly=True,
                                 default=lambda self: self.env['res.company']._company_default_get(
                                     'numa.account_retencion'))
    currency_id = fields.Many2one('res.currency', string=u'Moneda', store=True, readonly=True,
                                  related='company_id.currency_id')
    partner_ids = fields.One2many('numa.retention.partner', string="Razones Sociales", inverse_name="retention_id")
    display_retencion_name = fields.Char(string='Display Name')
    retencion_type = fields.Selection([], string="Retencion Type")
    devolution_option = fields.Selection(
        [('no_permite', 'No Permite'), ('solo_total', 'Solo Total'), ('sin_restriccion', u'Sin Restricción')],
        string=u'Permite Devolución?', default='sin_restriccion')
    address_type = fields.Selection([('fiscal', 'Domicilio Fiscal'), ('entrega', 'Domicilio de Entrega')],
                                    string="Address Type")
    scope = fields.Selection([('siempre', 'Aplicar Siempre'), ('country', 'Country'), ('state', 'State')],
                             default="siempre", string='Scope',
                             help='Aplicar Siempre: All scope\nCountry: country scope\nState: state scope')
    country_scope_ids = fields.Many2many(comodel_name='res.country', relation='numa_account_retencion_country_rel',
                                         column1="retencion_id", column2='country_id', string='Country Scope')
    state_scope_ids = fields.Many2many(comodel_name='res.country.state', relation='numa_account_retencion_state_rel',
                                       column1="retencion_id", column2="state_id", string='State Scope')
    calculation_module = fields.Many2one('numa.calculation_module', 'Module', domain="[('module_type','=','ret_perc')]")
    calculation_type = fields.Selection(
        [('basic', u'Básico'), ('module', u'Módulo'), ('python_code', u'Código Python')], string="Tipo de Cálculo",
        default='basic')
    python_code = fields.Text('Python Code')
    percent = fields.Float('Porcentaje', digits=(3, 2))
    minimo_no_imponible = fields.Monetary(u'Mínimo No Imponible')
    retencion_minima = fields.Monetary(u'Retención Mínima')
    account_sale_id = fields.Many2one('account.account', 'Cuenta Ventas', required=True, company_dependent=True)
    account_sale_id_devolution = fields.Many2one('account.account', u'Cuenta Devolución Venta', required=True,
                                                 company_dependent=True)
    account_purchase_id = fields.Many2one('account.account', 'Cuenta Compras', required=True, company_dependent=True)
    account_purchase_id_devolution = fields.Many2one('account.account', u'Cuenta Devolución Compras', required=True,
                                                     company_dependent=True)
    account_liquidation_id = fields.Many2one('account.account', u'Cuenta Retenciones Liquidadas',
                                             company_dependent=True)
    account_payment_id = fields.Many2one('account.account', u'Cuenta Retenciones Pagadas', company_dependent=True)
    monto_base = fields.Selection([('neto', 'Neto'), ('bruto', 'Bruto')], string="Monto Base")
    resolution_ids = fields.Many2many(comodel_name='numa.resolution.retention_perception',
                                      relation='numa_account_retention_resolution_rel', column1="retention_id",
                                      column2='resolution_id', string='Resoluciones')
    ok_servicios = fields.Boolean('Servicios?', default=True)
    ok_bienes_cambio = fields.Boolean('Bienes Cambio?', default=True)
    ok_bienes_uso = fields.Boolean('Bienes Uso?', default=False)
    active = fields.Boolean('Active', default=True)


    note = fields.Text('Notes')

    @api.model
    def compute_retenciones(self,
                            amount=0.0,
                            currency=None,
                            payer=None,
                            payed=None,
                            payment_date=None,
                            ):
        # Asume que self está en la compañía del documento a generar
        # Retorna una lista de diccionarios con los siguientes valores
        #     currency_amount,
        #     original_currency_id,
        #     withholding_type_id,
        #     account_id,
        #     amount

        # Todo

        return []


class numa_account_percepcion(models.Model):
    _name = 'numa.account_percepcion'

    name = fields.Char(string=u'Percepción', required=True)
    code = fields.Char(string='Code')
    company_id = fields.Many2one('res.company', string='Company', change_default=True, required=True, readonly=True,
                                 default=lambda self: self.env['res.company']._company_default_get(
                                     'numa.account_percepcion'))
    currency_id = fields.Many2one('res.currency', string=u'Moneda', store=True, readonly=True,
                                  related='company_id.currency_id')
    partner_ids = fields.One2many('numa.perception.partner', string="Razones Sociales", inverse_name="perception_id")
    display_perception_name = fields.Char(string='Display Name')
    percepcion_type = fields.Selection([], string="Percepcion Type")
    devolution_option = fields.Selection(
        [('no_permite', 'No Permite'), ('solo_total', 'Solo Total'), ('sin_restriccion', u'Sin Restricción')],
        string=u'Permite Devolución?', default='sin_restriccion')
    address_type = fields.Selection([('fiscal', 'Domicilio Fiscal'), ('entrega', 'Domicilio de Entrega')],
                                    string="Address Type")
    scope = fields.Selection([('siempre', 'Aplicar Siempre'), ('country', 'Country'), ('state', 'State')],
                             default="siempre", string='Scope',
                             help='Aplicar Siempre: All scope\nCountry: country scope\nState: state scope')
    country_scope_ids = fields.Many2many(comodel_name='res.country', relation='numa_account_percepcion_country_rel',
                                         column1="percepcion_id", column2='country_id', string='Country Scope')
    state_scope_ids = fields.Many2many(comodel_name='res.country.state', relation='numa_account_percepcion_state_rel',
                                       column1="percepcion_id", column2="state_id", string='State Scope')
    calculation_module = fields.Many2one('numa.calculation_module', 'Calculation Module',
                                         domain="[('module_type','=','ret_perc')]")
    calculation_type = fields.Selection(
        [('basic', u'Básico'), ('module', u'Módulo'), ('python_code', u'Código Python')], string="Tipo de Cálculo",
        default='basic')
    python_code = fields.Text('Python Code')
    percent = fields.Float('Porcentaje', digits=(3, 2))
    minimo_no_imponible = fields.Monetary(u'Mínimo No Imponible')
    percepcion_minima = fields.Monetary(u'Percepción Mínima')
    account_sale_id = fields.Many2one('account.account', 'Cuenta Ventas', required=True, company_dependent=True)
    account_sale_id_devolution = fields.Many2one('account.account', u'Cuenta Devolución Venta', required=True,
                                                 company_dependent=True)
    account_purchase_id = fields.Many2one('account.account', 'Cuenta Compras', required=True, company_dependent=True)
    account_purchase_id_devolution = fields.Many2one('account.account', u'Cuenta Devolución Compras', required=True,
                                                     company_dependent=True)
    account_liquidation_id = fields.Many2one('account.account', u'Cuenta Percepciones Liquidadas',
                                             company_dependent=True)
    account_payment_id = fields.Many2one('account.account', u'Cuenta Percepciones Pagadas', company_dependent=True)
    monto_base = fields.Selection([('neto', 'Neto'), ('bruto', 'Bruto')], string="Monto Base", default='neto')
    resolution_ids = fields.Many2many(comodel_name='numa.resolution.retention_perception',
                                      relation='numa_account_perception_resolution_rel', column1="perception_id",
                                      column2='resolution_id', string='Resoluciones')
    ok_servicios = fields.Boolean('Servicios?', default=True)
    ok_bienes_cambio = fields.Boolean('Bienes Cambio?', default=True)
    ok_bienes_uso = fields.Boolean('Bienes Uso?', default=False)
    active = fields.Boolean('Active', default=True)
    note = fields.Text('Notes')


class numa_calculation_module(models.Model):
    _name = 'numa.calculation_module'

    name = fields.Char(string='Name', required=True)
    module_type = fields.Selection([('iva', 'IVA'),
                                    ('ret_perc', 'Retenciones y Percepciones'),
                                    ('ganancias', 'Ganancias'), ('suss', 'SUSS')], string="Module Type")
    function_name = fields.Char(string='Function Name', required=True)

class numa_perception_partner(models.Model):
    _name = 'numa.perception.partner'
    _rec_name = 'perception_id'

    perception_id = fields.Many2one('numa.account_percepcion', u'Percepción')
    partner_id = fields.Many2one('res.partner', u'Razón Social')
    agent_recaudation = fields.Boolean(u'Agente de Recaudación')
    exento = fields.Boolean('Exento?')
    resolution_ids = fields.One2many('numa.resolution.perception.partner', string="Resoluciones",
                                     inverse_name="perception_partner_id")
    note = fields.Text('Notas')


class numa_resolution_perception_partner(models.Model):
    _name = 'numa.resolution.perception.partner'
    _rec_name = 'perception_partner_id'

    perception_partner_id = fields.Many2one('numa.perception.partner', u'Percepción')
    resolution_id = fields.Many2one('numa.resolution.retention_perception', u'Resolución')
    resolution_filename = fields.Char(string='Filename')
    resolution_file = fields.Binary(string='File', filename="filename")
    date_end = fields.Date(string='Vencimiento')
    special_percent = fields.Float('Porcentaje Especial', digits=(3, 2))
    note = fields.Text('Notas')


class numa_retention_partner(models.Model):
    _name = 'numa.retention.partner'
    _rec_name = 'retention_id'

    retention_id = fields.Many2one('numa.account_retencion', u'Retención')
    partner_id = fields.Many2one('res.partner', u'Razón Social')
    agent_recaudation = fields.Boolean(u'Agente de Recaudación')
    exento = fields.Boolean('Exento?')
    resolution_ids = fields.One2many('numa.resolution.retention.partner', string="Resoluciones",
                                     inverse_name="retention_partner_id")
    note = fields.Text('Notas')


class numa_resolution_retention_partner(models.Model):
    _name = 'numa.resolution.retention.partner'
    _rec_name = 'retention_partner_id'

    retention_partner_id = fields.Many2one('numa.retention.partner', u'Retención')
    resolution_id = fields.Many2one('numa.resolution.retention_perception', u'Resolución')
    resolution_filename = fields.Char(string='Filename')
    resolution_file = fields.Binary(string='File', filename="filename")
    date_end = fields.Date(string='Vencimiento')
    special_percent = fields.Float('Porcentaje Especial', digits=(3, 2))
    note = fields.Text('Notas')


class numa_resolution_retention_perception(models.Model):
    _name = 'numa.resolution.retention_perception'

    name = fields.Char(string=u'Resolución', required=True)
    retention_ids = fields.Many2many(comodel_name='numa.account_retencion',
                                     relation='numa_account_retention_resolution_rel', column1="resolution_id",
                                     column2='retention_id', string='Retenciones')
    perception_ids = fields.Many2many(comodel_name='numa.account_percepcion',
                                      relation='numa_account_perception_resolution_rel', column1="resolution_id",
                                      column2='perception_id', string='Percepciones')
    description = fields.Char(string=u'Descripción')
    note = fields.Text('Notas')


class numa_partner_retencion_percepcion(models.Model):
    _inherit = 'res.partner'

    retencion_ids = fields.One2many('numa.retention.partner', string="Retenciones", inverse_name="partner_id")
    percepcion_ids = fields.One2many('numa.perception.partner', string="Percepciones", inverse_name="partner_id")


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    amount_perceptions = fields.Monetary(string=u'Percepciones', store=True, readonly=True, compute='_compute_amount',
                                         track_visibility='always')
    amount_base_perceptions = fields.Monetary(string=u'Base Percepciones', store=True, readonly=True, compute='_compute_amount')
    amount_with_perceptions = fields.Monetary(string=u'Total', store=True, readonly=True, compute='_compute_amount')
    perception_ids = fields.One2many('numa.account.invoice.perception', 'invoice_id', string=u'Percepciones',
                                     readonly=True, states={'draft': [('readonly', False)]}, copy=False)

    @api.one
    @api.depends('invoice_line_ids.price_subtotal', 'tax_line_ids.amount', 'currency_id', 'company_id', 'date_invoice',
                 'type', 'perception_ids')
    def _compute_amount(self):
        super(AccountInvoice, self)._compute_amount()
        round_curr = self.currency_id.round
        amount_perceptions = 0.0
        amount_base_perceptions = 0.0
        for line in self.perception_ids:
            amount_perceptions += line.amount
            amount_base_perceptions += line.base
        self.amount_perceptions = amount_perceptions
        self.amount_base_perceptions = amount_base_perceptions
        self.amount_total += self.amount_perceptions

    @api.model
    def perceptions_move_line_get(self):
        res = []
        # loop the invoice.perception_ids in reversal sequence
        for pl in self.perception_ids:
            res.append({
                'name': pl.name,
                'price_unit': pl.amount,
                'quantity': 1,
                'price': pl.amount,
                'account_id': pl.account_id.id,
                'invoice_id': self.id,
            })
        return res

    @api.model
    def tax_line_move_line_get(self):
        res = super(AccountInvoice, self).tax_line_move_line_get()
        res += self.perceptions_move_line_get()
        return res

    @api.onchange('invoice_line_ids')
    def _onchange_invoice_perception_ids(self):
        super(AccountInvoice, self)._onchange_invoice_line_ids()
        if not self.afip_tipo_doc_number or not self.amount_untaxed:
            return
        perception_grouped = self.get_perception_values()
        perception_lines = self.perception_ids.filtered('manual')
        perception_total = 0.0
        for perception in perception_grouped.values():
            perception_lines += perception_lines.new(perception)
            perception_total += perception['amount']
        self.perception_ids = perception_lines
        return

    @api.multi
    def get_perception_values(self):
        perception_grouped = {}

        for invoice in self:
            if invoice.invoice_line_ids:
                if invoice.company_id.partner_id.percepcion_ids:
                    for perception in invoice.company_id.partner_id.percepcion_ids:
                        if perception.agent_recaudation and perception.perception_id.active:
                            if perception.perception_id.address_type == 'fiscal':
                                partner_address_id = invoice.partner_id
                            else:
                                partner_address_id = invoice.partner_shipping_id
                            # Perception Application Scope
                            if perception.perception_id.scope == 'country' and perception.perception_id.country_scope_ids:
                                if partner_address_id.country_id not in perception.perception_id.country_scope_ids:
                                    continue
                            elif perception.perception_id.scope == 'state' and perception.perception_id.state_scope_ids:
                                if partner_address_id.state_id not in perception.perception_id.state_scope_ids:
                                    continue

                            # Perception Application Partner
                            monto_base = amount = 0.0
                            name_add = ''
                            exento = False
                            percent = perception.perception_id.percent or 0.0
                            if invoice.partner_id.percepcion_ids:
                                for partner in invoice.partner_id.percepcion_ids:
                                    if partner.perception_id.id == perception.perception_id.id:
                                        if partner.exento:
                                            fechas = 0
                                            exento = True
                                            name_add = _(' (Exento)')
                                            break

                            if not exento:
                                amount_untaxed = invoice.amount_untaxed
                                amount_tax = invoice.amount_tax
                                for line in invoice.invoice_line_ids:
                                    if line.bien_de_uso:
                                        amount_untaxed -= line.price_subtotal
                                        amount_tax -= line.price_subtotal  # calcular taxes
                                if perception.perception_id.monto_base == 'neto':
                                    monto_base = amount_untaxed
                                else:
                                    monto_base = amount_untaxed + amount_tax
                                self.amount_base_perceptions = monto_base

                                if perception.perception_id.calculation_type == 'module':
                                    if perception.perception_id.calculation_module:
                                        ncm_obj = self.env['numa.calculation_module']
                                        (amount, name_add, monto_base, percent) = getattr(ncm_obj,perception.perception_id.calculation_module.function_name)(invoice,False)
                                elif perception.perception_id.calculation_type == 'python_code':
                                    if perception.perception_id.python_code:
                                        dict_res = {'invoice': invoice, 'amount': 0.0, 'percent': 0.0}
                                        exec perception.perception_id.python_code in dict_res
                                        amount = dict_res.get('amount', 0.0)
                                        percent = dict_res.get('percent', 0.0)
                                else:
                                    if monto_base > perception.perception_id.minimo_no_imponible:
                                        amount = (monto_base - perception.perception_id.minimo_no_imponible) * percent / 100
                                        if amount < perception.perception_id.percepcion_minima:
                                            amount = 0.0

                            if amount <> 0 or exento:
                                name = perception.perception_id.name and perception.perception_id.display_perception_name or 'Nombre Indefinido'
                                vals = {'name': name + name_add,
                                        'invoice_id': invoice.id,
                                        'base': monto_base,
                                        'amount': amount,
                                        'percent': percent,
                                        'perception_id': perception.perception_id.id,
                                        'account_id': perception.perception_id.account_sale_id.id,
                                        'manual': False,
                                        'state': 'confirmed',
                                        'type_perception': 'sale'}

                                if perception.perception_id.id not in perception_grouped:
                                    perception_grouped[perception.perception_id.id] = vals
                                else:
                                    perception_grouped[perception.perception_id.id]['amount'] += vals['amount']
                                    perception_grouped[perception.perception_id.id]['base'] += vals['base']

        return perception_grouped


class AccountInvoicePerception(models.Model):
    _name = 'numa.account.invoice.perception'

    invoice_id = fields.Many2one('account.invoice', string='Invoice', ondelete='cascade')
    name = fields.Char(u'Percepción')
    base = fields.Monetary(string=u'Base Cálculo', readonly=True)
    amount = fields.Monetary(string=u'Monto', readonly=True)
    currency_id = fields.Many2one('res.currency', string=u'Moneda', store=True, readonly=True,
                                  related='invoice_id.currency_id')
    perception_id = fields.Many2one('numa.account_percepcion', string=u'Percepción', ondelete='restrict')
    account_id = fields.Many2one('account.account', string=u'Cuenta Percepción', required=True)
    manual = fields.Boolean(default=True)
    type_perception = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase')], string='Tipo', readonly=True)

    date = fields.Date(string='Fecha', related='invoice_id.date_invoice', store=True, readonly=True)
    partner = fields.Char('Empresa', related='invoice_id.partner_id.name', store=True, readonly=True)
    company = fields.Char(string=u'Company', related='invoice_id.company_id.name', store=True, readonly=True)
    percent = fields.Float('Porcentaje', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed')], string='State')

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    amount_perceptions = fields.Monetary(string=u'Percepciones', store=True, readonly=True, compute='_amount_all',
                                         track_visibility='always')
    amount_with_perceptions = fields.Monetary(string=u'Total', store=True, readonly=True, compute='_amount_all')
    perception_ids = fields.One2many('numa.sale.order.perception', 'sale_order_id', string=u'Percepciones',
                                     readonly=True, states={'draft': [('readonly', False)]}, copy=False)

    @api.one
    @api.depends('order_line.price_subtotal', 'tax_line_ids.amount', 'currency_id', 'company_id', 'perception_ids')
    def _amount_all(self):
        super(SaleOrder, self)._amount_all()
        round_curr = self.currency_id.round
        self.amount_perceptions = sum(round_curr(line.amount) for line in self.perception_ids)
        self.amount_total += self.amount_perceptions

    #@api.multi
    #def compute_taxes(self):
        #super(SaleOrder, self).compute_taxes()
        #self.compute_perceptions()

    @api.onchange('order_line')
    def _onchange_sale_order_perception_ids(self):
        super(SaleOrder, self)._onchange_order_line()

        perception_grouped = self.get_perception_values()
        perception_lines = self.perception_ids.filtered('manual')
        perception_total = 0.0
        for perception in perception_grouped.values():
            perception_lines += perception_lines.new(perception)
            perception_total += perception['amount']
        self.perception_ids = perception_lines
        self.amount_perceptions = perception_total
        return

    @api.multi
    def get_perception_values(self):
        perception_grouped = {}
        for sale_order in self:
            if sale_order.order_line:
                if sale_order.company_id.partner_id.percepcion_ids:
                    for perception in sale_order.company_id.partner_id.percepcion_ids:
                        if perception.agent_recaudation and perception.perception_id.active:
                            if perception.perception_id.address_type == 'fiscal':
                                partner_address_id = sale_order.partner_id
                            else:
                                partner_address_id = sale_order.partner_shipping_id
                            # Perception Application Scope
                            if perception.perception_id.scope == 'country' and perception.perception_id.country_scope_ids:
                                if partner_address_id.country_id not in perception.perception_id.country_scope_ids:
                                    continue
                            elif perception.perception_id.scope == 'state' and perception.perception_id.state_scope_ids:
                                if partner_address_id.state_id not in perception.perception_id.state_scope_ids:
                                    continue

                            # Perception Application Partner
                            monto_base = amount = 0.0
                            name_add = ''
                            exento = False
                            percent = perception.perception_id.percent or 0.0
                            if sale_order.partner_id.percepcion_ids:
                                for partner in sale_order.partner_id.percepcion_ids:
                                    if partner.perception_id.id == perception.perception_id.id:
                                        if partner.exento:
                                            fechas = 0
                                            exento = False
                                            name_add = _(' (Exento)')
                                            break

                            if not exento:
                                monto_base = 0.0
                                for sol in sale_order.order_line:
                                    if not sol.bien_de_uso:
                                        if perception.perception_id.monto_base != 'neto':
                                            monto_base += sol.price_subtotal
                                        else:
                                            monto_base += sol.price_total

                                if perception.perception_id.calculation_type == 'module':
                                    if perception.perception_id.calculation_module:
                                        ncm_obj = self.env['numa.calculation_module']
                                        (amount, name_add, monto_base, percent) = getattr(ncm_obj,perception.perception_id.calculation_module.function_name)(False,sale_order)
                                elif perception.perception_id.calculation_type == 'python_code':
                                    if perception.perception_id.python_code:
                                        dict_res = {'sale_order': sale_order, 'amount': 0.0, 'percent': 0.0}
                                        exec perception.perception_id.python_code in dict_res
                                        amount = dict_res.get('amount', 0.0)
                                        percent = dict_res.get('percent', 0.0)
                                else:
                                    if monto_base > perception.perception_id.minimo_no_imponible:
                                        amount = (monto_base - perception.perception_id.minimo_no_imponible) * percent / 100
                                        if amount < perception.perception_id.percepcion_minima:
                                            amount = 0.0

                            if amount <> 0 or exento:
                                name = perception.perception_id.name and perception.perception_id.display_perception_name or 'Nombre Indefinido'
                                vals = {'name': name + name_add,
                                        'sale_order_id': sale_order.id,
                                        'base': monto_base,
                                        'amount': amount,
                                        'percent': percent,
                                        'perception_id': perception.perception_id.id,
                                        'account_id': perception.perception_id.account_sale_id.id,
                                        'manual': False,
                                        'state': 'confirmed',
                                        'type_perception': 'sale'}

                                if perception.perception_id.id not in perception_grouped:
                                    perception_grouped[perception.perception_id.id] = vals
                                else:
                                    perception_grouped[perception.perception_id.id]['amount'] += vals['amount']
                                    perception_grouped[perception.perception_id.id]['base'] += vals['base']

        return perception_grouped

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    amount_perceptions = fields.Monetary(string=u'Percepciones', store=True, readonly=True, compute='_amount_all',track_visibility='always')
    amount_with_perceptions = fields.Monetary(string=u'Total', store=True, readonly=True, compute='_amount_all')
    perception_ids = fields.One2many('numa.purchase.order.perception', 'purchase_order_id', string=u'Percepciones',
                                     readonly=True, states={'draft': [('readonly', False)]}, copy=False)

    @api.one
    @api.depends('order_line.price_subtotal', 'tax_line_ids.amount', 'currency_id', 'company_id', 'perception_ids')
    def _amount_all(self):
        super(PurchaseOrder, self)._amount_all()
        round_curr = self.currency_id.round
        self.amount_perceptions = sum(round_curr(line.amount) for line in self.perception_ids)
        self.amount_total += self.amount_perceptions

    #@api.multi
    #def compute_taxes(self):
        #super(SaleOrder, self).compute_taxes()
        #self.compute_perceptions()

    @api.onchange('order_line')
    def _onchange_purchase_order_perception_ids(self):
        super(PurchaseOrder, self)._onchange_order_line()

        perception_grouped = self.get_perception_values()
        perception_lines = self.perception_ids.filtered('manual')
        perception_total = 0.0
        for perception in perception_grouped.values():
            perception_lines += perception_lines.new(perception)
            perception_total += perception['amount']
        self.perception_ids = perception_lines
        self.amount_perceptions = perception_total
        return

    @api.multi
    def get_perception_values(self):
        perception_grouped = {}
        for purchase_order in self:
            if purchase_order.order_line:
                if purchase_order.company_id.partner_id.percepcion_ids:
                    for perception in purchase_order.company_id.partner_id.percepcion_ids:
                        if perception.agent_recaudation and perception.perception_id.active:
                            if perception.perception_id.address_type == 'fiscal':
                                partner_address_id = purchase_order.partner_id
                            else:
                                partner_address_id = purchase_order.partner_id
                            # Perception Application Scope
                            if perception.perception_id.scope == 'country' and perception.perception_id.country_scope_ids:
                                if partner_address_id.country_id not in perception.perception_id.country_scope_ids:
                                    continue
                            elif perception.perception_id.scope == 'state' and perception.perception_id.state_scope_ids:
                                if partner_address_id.state_id not in perception.perception_id.state_scope_ids:
                                    continue

                            # Perception Application Partner
                            monto_base = amount = 0.0
                            name_add = ''
                            exento = False
                            percent = perception.perception_id.percent or 0.0
                            if purchase_order.partner_id.percepcion_ids:
                                for partner in purchase_order.partner_id.percepcion_ids:
                                    if partner.perception_id.id == perception.perception_id.id:
                                        if partner.exento:
                                            fechas = 0
                                            exento = False
                                            name_add = _(' (Exento)')
                                            break

                            if not exento:
                                monto_base = 0.0
                                for sol in purchase_order.order_line:
                                    if not sol.bien_de_uso:
                                        if perception.perception_id.monto_base != 'neto':
                                            monto_base += sol.price_subtotal
                                        else:
                                            monto_base += sol.price_total

                                if perception.perception_id.calculation_type == 'module':
                                    if perception.perception_id.calculation_module:
                                        ncm_obj = self.env['numa.calculation_module']
                                        (amount, name_add, monto_base, percent) = getattr(ncm_obj,perception.perception_id.calculation_module.function_name)(False,purchase_order)
                                elif perception.perception_id.calculation_type == 'python_code':
                                    if perception.perception_id.python_code:
                                        dict_res = {'purchase_order': purchase_order, 'amount': 0.0, 'percent': 0.0}
                                        exec perception.perception_id.python_code in dict_res
                                        amount = dict_res.get('amount', 0.0)
                                        percent = dict_res.get('percent', 0.0)
                                else:
                                    if monto_base > perception.perception_id.minimo_no_imponible:
                                        amount = (monto_base - perception.perception_id.minimo_no_imponible) * percent / 100
                                        if amount < perception.perception_id.percepcion_minima:
                                            amount = 0.0

                            if amount <> 0 or exento:
                                name = perception.perception_id.name and perception.perception_id.display_perception_name or 'Nombre Indefinido'
                                vals = {'name': name + name_add,
                                        'purchase_order_id': purchase_order.id,
                                        'base': monto_base,
                                        'amount': amount,
                                        'percent': percent,
                                        'perception_id': perception.perception_id.id,
                                        'account_id': perception.perception_id.account_sale_id.id,
                                        'manual': False,
                                        'state': 'confirmed',
                                        'type_perception': 'purchase'}

                                if perception.perception_id.id not in perception_grouped:
                                    perception_grouped[perception.perception_id.id] = vals
                                else:
                                    perception_grouped[perception.perception_id.id]['amount'] += vals['amount']
                                    perception_grouped[perception.perception_id.id]['base'] += vals['base']

        return perception_grouped


class SaleOrderPerception(models.Model):
    _name = 'numa.sale.order.perception'

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', ondelete='cascade')
    name = fields.Char(u'Percepción')
    base = fields.Monetary(string=u'Base Cálculo', readonly=True)
    amount = fields.Monetary(string=u'Monto', readonly=True)
    currency_id = fields.Many2one('res.currency', string=u'Moneda', store=True, readonly=True, related='sale_order_id.currency_id')
    perception_id = fields.Many2one('numa.account_percepcion', string=u'Percepción', ondelete='restrict')
    account_id = fields.Many2one('account.account', string=u'Cuenta Percepción', required=True)
    manual = fields.Boolean(default=True)
    type_perception = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase')], string='Tipo', readonly=True)

    date = fields.Datetime(string='Fecha', related='sale_order_id.confirmation_date', store=True, readonly=True)
    partner = fields.Char('Empresa', related='sale_order_id.partner_id.name', store=True, readonly=True)
    company = fields.Char(string=u'Company', related='sale_order_id.company_id.name', store=True, readonly=True)
    percent = fields.Float('Porcentaje', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed')], string='State')

class PurchaseOrderPerception(models.Model):
    _name = 'numa.purchase.order.perception'

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', ondelete='cascade')
    name = fields.Char(u'Percepción')
    base = fields.Monetary(string=u'Base Cálculo', readonly=True)
    amount = fields.Monetary(string=u'Monto', readonly=True)
    currency_id = fields.Many2one('res.currency', string=u'Moneda', store=True, readonly=True, related='purchase_order_id.currency_id')
    perception_id = fields.Many2one('numa.account_percepcion', string=u'Percepción', ondelete='restrict')
    account_id = fields.Many2one('account.account', string=u'Cuenta Percepción', required=True)
    manual = fields.Boolean(default=True)
    type_perception = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase')], string='Tipo', readonly=True)

    date = fields.Date(string='Fecha', related='purchase_order_id.date_approve', store=True, readonly=True)
    partner = fields.Char('Empresa', related='purchase_order_id.partner_id.name', store=True, readonly=True)
    company = fields.Char(string=u'Company', related='purchase_order_id.company_id.name', store=True, readonly=True)
    percent = fields.Float('Porcentaje', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed')], string='State')

class AccountPaymentRetention(models.Model):
    _name = 'numa.account.payment.retention'

    retention_type = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase')], string='Tipo')
    partner_id = fields.Many2one('res.partner', 'Partner')
    name = fields.Char(u'Retención')
    base = fields.Monetary(string=u'Base Cálculo')
    currency_id = fields.Many2one('res.currency', 'Currency')

    date = fields.Date('Date')
    retention_id = fields.Many2one('numa.account_retencion', 'Retention')
    retention_number = fields.Char('Number')
    retention_file = fields.Binary('File')

    account_id = fields.Many2one('account.account', 'Account', domain="[('company_id','=',company_id),('deprecated', '=', False)]")
    manual = fields.Boolean(default=True)
    percent = fields.Float('Porcentaje', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed')], string='State')



