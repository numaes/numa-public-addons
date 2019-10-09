from odoo import fields, models, api
from odoo.tools.translate import _
from odoo.exceptions import ValidationError
from datetime import datetime, date, timedelta
import base64
import zipfile
import StringIO
import re

import logging

_logger = logging.getLogger(__name__)


class numa_partner_extended(models.Model):
    _inherit = 'res.partner'

    @api.one
    @api.depends('credit_current_account_customer', 'credit_checks_own_customer', 'credit_checks_third_customer',
                 'credit_documents_customer', 'credit_card_customer')
    def _compute_credit_total_customer(self):
        for credit in self:
            credit.credit_total_customer = credit.credit_current_account_customer + credit.credit_checks_own_customer + credit.credit_checks_third_customer + credit.credit_documents_customer + credit.credit_card_customer

    @api.one
    @api.depends('credit_current_account_supplier', 'credit_checks_own_supplier', 'credit_checks_third_supplier',
                 'credit_documents_supplier', 'credit_card_supplier')
    def _compute_credit_total_supplier(self):
        for credit in self:
            credit.credit_total_supplier = credit.credit_current_account_supplier + credit.credit_checks_own_supplier + credit.credit_checks_third_supplier + credit.credit_documents_supplier + credit.credit_card_supplier

    profile_payment_customer_id = fields.Many2one(comodel_name='numa.profile_payment',
                                                  domain="[('partner_domain','in',['customer','customer_supplier'])]",
                                                  string='Profile Payment Customer', ondelete="restrict")
    profile_payment_supplier_id = fields.Many2one(comodel_name='numa.profile_payment',
                                                  domain="[('partner_domain','in',['supplier','customer_supplier'])]",
                                                  string='Profile Payment Supplier', ondelete="restrict")
    credit_profile_customer = fields.Selection([('no_credit', 'No Credit'), ('credit', 'Credit Granted')],
                                               string='Credit Profile', default='no_credit', required=True)
    credit_current_account_customer = fields.Float(string="Current Account", digits=(16, 2), default=0.0)
    credit_checks_own_customer = fields.Float(string="Checks Own", digits=(16, 2), default=0.0)
    credit_checks_third_customer = fields.Float(string="Checks Third", digits=(16, 2), default=0.0)
    credit_documents_customer = fields.Float(string="Documents", digits=(16, 2), default=0.0)
    credit_card_customer = fields.Float(string="Credit Card", digits=(16, 2), default=0.0)
    credit_total_customer = fields.Float(string="Credit Total", compute='_compute_credit_total_customer',
                                         digits=(16, 2), store=True)
    credit_profile_supplier = fields.Selection([('no_credit', 'No Credit'), ('credit', 'Credit')],
                                               string='Credit Profile', default='no_credit', required=True)
    credit_current_account_supplier = fields.Float(string="Current Account", digits=(16, 2), default=0.0)
    credit_checks_own_supplier = fields.Float(string="Checks Own", digits=(16, 2), default=0.0)
    credit_checks_third_supplier = fields.Float(string="Checks Third", digits=(16, 2), default=0.0)
    credit_documents_supplier = fields.Float(string="Documents", digits=(16, 2), default=0.0)
    credit_card_supplier = fields.Float(string="Credit Card", digits=(16, 2), default=0.0)
    credit_total_supplier = fields.Float(string="Credit Total", compute='_compute_credit_total_supplier',
                                         digits=(16, 2), store=True)

    fantasy_name = fields.Char(string='Nombre Fantasia')

    property_product_pricelist = fields.Many2one(
        'product.pricelist', 'Sale Pricelist', company_dependent=True,
        compute=False, inverse=False,
        help="This pricelist will be used, instead of the default one, for sales to the current partner")

    property_supplier_product_pricelist = fields.Many2one(
        'product.pricelist', 'Purchase Pricelist', company_dependent=True,
        compute=False, inverse=False,
        help="This pricelist will be used, instead of the default one, for purchase to the current partner")

    company_child_ids = fields.One2many('res.partner','parent_id','Sub Empresas', domain=[('active','=',True),('is_company','=',True)])


    def action_current_account(self):
        self.ensure_one()
        account_current_account = self.env['account.current_account']
        account_current = account_current_account.create({'partner_id':self.id})
        account_current.action_refresh_account_current()

        return {
            'name': _("Partner's Current Account"),
            'view_mode': 'form',
            'view_type': 'form',
            'res_model': 'account.current_account',
            'res_id': account_current.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
            'nodestroy': True,
            'flags': {'form': {'action_buttons': False}, 'initial_mode': 'edit'},
        }


class numa_profile_payment(models.Model):
    _name = 'numa.profile_payment'

    name = fields.Char(string='Profile Payment', required=True)
    partner_domain = fields.Selection(
        [('customer', 'Customer'), ('supplier', 'Supplier'), ('customer_supplier', 'Customer and Supplier')],
        string='Profile Domain', required=True)
    payment_term_ids = fields.Many2many(comodel_name='account.payment.term', relation='numa_profile_payment_rel',
                                        column1='profile_id', column2='payment_term_id', string='Payment Terms')
    note = fields.Text('Notas')

class numa_account_payment_term(models.Model):
    _inherit = 'account.payment.term'

    profile_payment_ids = fields.Many2many(comodel_name='numa.profile_payment', relation='numa_profile_payment_rel',
                                           column1='payment_term_id', column2='profile_id', string='Profile Payment')


class PartnerCurrentAccount(models.TransientModel):
    _name = 'account.current_account'

    def _default_til_date(self):
        todayStr = fields.Date.context_today(self)

        return date(int(todayStr[0:4]), int(todayStr[5:7]), int(todayStr[8:10]))

    def _default_from_date(self):
        tilDate = self._default_til_date()
        return tilDate - timedelta(days=30)

    edit_field = fields.Boolean('Edit Field', default=False)
    partner_id = fields.Many2one('res.partner', 'Partner', required=True)
    image = fields.Binary('Image', related='partner_id.image', store=True, readonly=True)

    customer = fields.Boolean('Customer?', related='partner_id.customer', readonly=True)
    supplier = fields.Boolean('Supplier?', related='partner_id.supplier', readonly=True)

    customer_ok = fields.Boolean('Cliente ', default=True)
    supplier_ok = fields.Boolean('Supplier ', default=True)

    by_maturity =  fields.Boolean('Vencimiento 1/2/...?')
    with_balance = fields.Boolean('Pendientes')

    from_date = fields.Date('From', default=_default_from_date)
    til_date = fields.Date('Til', default=_default_til_date)

    orden_z_a = fields.Boolean('Z|A', default=False)

    include_children = fields.Boolean('Sub Empresas?')
    on_due_date = fields.Boolean('Orden Vencimiento?', help="Documents computed on due date or received date")
    subcompanies = fields.Boolean('Consider subcompanies?')

    current_balance_customer = fields.Monetary('Current Balance Customer', help="Current balance including not due documents")
    current_balance_supplier = fields.Monetary('Current Balance Supplier', help="Current balance including not due documents")
    todays_balance = fields.Monetary("Today's balance", help="Today's balance, without considering not due documents")
    check_customer_pending = fields.Monetary("Checks Customer", help="Cheks pending from customer")
    check_supplier_pending = fields.Monetary("Checks Supplier", help="Cheks pending to supplier")

    line_ids = fields.One2many('account.current_account.line', 'wizard_id', 'Detail')

    currency_id = fields.Many2one('res.currency', string="Currency")
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                 default=lambda self: self.env.user.company_id)

    profile_payment_customer_id = fields.Many2one('numa.profile_payment', string='Profile Payment Customer', related="partner_id.profile_payment_customer_id", readonly=True)
    profile_payment_supplier_id = fields.Many2one('numa.profile_payment', string='Profile Payment Supplier', related="partner_id.profile_payment_supplier_id", readonly=True)
    property_payment_term_id = fields.Many2one('account.payment.term', string='Plazo Pago', related="partner_id.property_payment_term_id", readonly=True)
    property_supplier_payment_term_id = fields.Many2one('account.payment.term', string='Plazo Pago', related="partner_id.property_supplier_payment_term_id", readonly=True)
    trust = fields.Selection(string='Etiqueta', related='partner_id.trust', readonly=True)

    credit_profile_customer = fields.Selection(string='Credit Profile', related='partner_id.credit_profile_customer', readonly=True)
    credit_current_account_customer = fields.Float(string="Current Account", related='partner_id.credit_current_account_customer', readonly=True)
    credit_checks_own_customer = fields.Float(string="Checks Own", related='partner_id.credit_checks_own_customer', readonly=True)
    credit_checks_third_customer = fields.Float(string="Checks Third", related='partner_id.credit_checks_third_customer', readonly=True)
    credit_documents_customer = fields.Float(string="Documents", related='partner_id.credit_documents_customer', readonly=True)
    credit_card_customer = fields.Float(string="Credit Card", related='partner_id.credit_card_customer', readonly=True)
    credit_total_customer = fields.Float(string="Credit Total", related='partner_id.credit_total_customer', readonly=True)

    credit_profile_supplier = fields.Selection(string='Credit Profile', related='partner_id.credit_profile_supplier', readonly=True)
    credit_current_account_supplier = fields.Float(string="Current Account", related='partner_id.credit_current_account_supplier', readonly=True)
    credit_checks_own_supplier = fields.Float(string="Checks Own", related='partner_id.credit_checks_own_supplier', readonly=True)
    credit_checks_third_supplier = fields.Float(string="Checks Third", related='partner_id.credit_checks_third_supplier', readonly=True)
    credit_documents_supplier = fields.Float(string="Documents", related='partner_id.credit_documents_supplier', readonly=True)
    credit_card_supplier = fields.Float(string="Credit Card", related='partner_id.credit_card_supplier', readonly=True)
    credit_total_supplier = fields.Float(string="Credit Total", related='partner_id.credit_total_supplier', readonly=True)

    check_customer_history = fields.Boolean('Historical')
    check_customer_ids = fields.One2many('account.current_account.check_customer', 'wizard_id', 'Checks Customer', readonly=True)

    check_supplier_history = fields.Boolean('Historical')
    check_supplier_ids = fields.One2many('account.current_account.check_supplier', 'wizard_id', 'Checks Supplier', readonly=True)

    @api.multi
    def name_get(self):
        res = []
        for a in self:
            res.append((a.id, 'Cuenta Corriente'))

        return res

    @api.onchange('company_id')
    def onchange_company_id(self):
        for wizard in self:
            if wizard.company_id:
                wizard.currency_id = wizard.company_id.currency_id.id

    @api.onchange('check_customer_history')
    def onchange_check_customer_history(self):
        if self.customer_ok:
            self.check_customer_ids = self.get_checks_customer()

    @api.onchange('check_supplier_history')
    def onchange_check_supplier_history(self):
        if self.supplier_ok:
            self.check_supplier_ids = self.get_checks_supplier()

    def print_current_account(self):
        return

    def compute_balance(self):
        partnerModel = self.env['res.partner']
        amlModel = self.env['account.move.line']
        companyModel = self.env['res.company']
        accountModel = self.env['account.account']

        for wizard in self:
            tables, where_clause, where_params = amlModel._query_get()
            partnerIds = [wizard.partner_id.id]
            if wizard.include_children:
                partnerIds = partnerModel.search([('id', 'child_of', [wizard.partner_id.id])]).ids

            companyIds = [wizard.company_id.id]
            if wizard.subcompanies:
                companyIds = companyModel.search([('id','child_of',companyIds)]).ids

            where_params = [tuple(companyIds), tuple(partnerIds)] + where_params
            if where_clause:
                where_clause = 'AND ' + where_clause

            wizard.current_balance_customer = 0.0
            wizard.current_balance_supplier = 0.0
            wizard.todays_balance = 0.0

            self._cr.execute("""
                          SELECT act.type as type, SUM(aml.debit) as debit, SUM(aml.credit) as credit
                          FROM account_move_line aml
                          INNER JOIN account_move am ON aml.move_id = am.id
                          INNER JOIN account_account a ON aml.account_id = a.id
                          LEFT JOIN account_account_type act ON a.user_type_id = act.id
                          WHERE am.state = 'posted' AND
                                am.company_id IN %s AND 
                                aml.partner_id IN %s AND
                                act.type IN ('receivable','payable')
                          """ + where_clause +
                          'GROUP BY act.type', where_params)

            for group_type in self._cr.fetchall():
                type, debit, credit = group_type
                if type == 'receivable':
                    wizard.current_balance_customer = (debit or 0.0) - (credit or 0.0)
                if type == 'payable':
                    wizard.current_balance_supplier = (debit or 0.0) - (credit or 0.0)

            date = datetime.strptime(wizard.from_date, '%Y-%m-%d') - timedelta(days=1)
            where_params = [date] + where_params

            param_partner_type = []
            if wizard.customer_ok:
                param_partner_type.append('receivable')

            if wizard.supplier_ok:
                param_partner_type.append('payable')

            where_params.append(tuple(param_partner_type))

            debit = 0.0
            credit = 0.0
            if param_partner_type:
                self._cr.execute("""
                              SELECT SUM(aml.debit) as debit, SUM(aml.credit) as credit
                              FROM account_move_line aml
                              INNER JOIN account_move am ON aml.move_id = am.id
                              INNER JOIN account_account a ON aml.account_id = a.id
                              LEFT JOIN account_account_type act ON a.user_type_id = act.id
                              WHERE aml.date <= %s AND
                                    am.state = 'posted' AND
                                    am.company_id IN %s AND 
                                    aml.partner_id IN %s AND
                                    act.type IN %s
                              """ + where_clause, where_params)

                debit, credit = self._cr.fetchall()[0]
            wizard.todays_balance = (debit or 0.0) - (credit or 0.0)

    def get_move_lines(self):
        partnerModel = self.env['res.partner']
        amlModel = self.env['account.move.line']
        companyModel = self.env['res.company']

        self.ensure_one()
        wizard = self

        partnerIds = [wizard.partner_id.id]
        if wizard.include_children:
            partnerIds = partnerModel.search([('id', 'child_of', [wizard.partner_id.id])]).ids

        companyIds = [wizard.company_id.id]
        if wizard.subcompanies:
            companyIds = companyModel.search([('id', 'child_of', companyIds)]).ids

        account_type = []
        if wizard.customer and wizard.customer_ok:
            account_type.append('receivable')
        if wizard.supplier and wizard.supplier_ok:
            account_type.append('payable')

        searchCondition = [('move_id.company_id', 'in', companyIds),
                           ('move_id.state', '=', 'posted'),
                           ('partner_id', 'in', partnerIds),
                           ('account_id.user_type_id.type', 'in', account_type),]

        if wizard.on_due_date:
            searchCondition += [('date_maturity', '>=', wizard.from_date),('date_maturity', '<=', wizard.til_date),]
        else:
            searchCondition += [('date', '>=', wizard.from_date), ('date', '<=', wizard.til_date),]


        if wizard.with_balance:
            searchCondition += [('balance','!=',0.0)]

        orderClause = 'date_maturity asc' if wizard.on_due_date else 'date asc'

        amls = amlModel.search(searchCondition, order=orderClause+', invoice_id')

        return amls

    def get_checks_customer(self):
        thirdpartycheckModel = self.env['account.third_party_check']
        if self.check_customer_history:
            searchCondition = [('received_from','=',self.partner_id.id),
                               ('state','not in',['draft'])]
        else:
            searchCondition = [('received_from', '=', self.partner_id.id),
                               ('payment_date','>=',fields.Date.context_today(self)),
                               ('state','not in',['draft','reject','canceled'])]

        ids = thirdpartycheckModel.search(searchCondition)
        check_ids = []
        if ids:
            amount_total = 0.0
            for id in ids:
                amount_total += id.amount
                vals = {'wizard_id': self.id,
                        'check_id': id.id}
                check_customer_id = self.check_customer_ids.create(vals).id
                check_ids.append(check_customer_id)

            if not self.check_customer_history:
                self.check_customer_pending = amount_total

        return check_ids

    def get_checks_supplier(self):
        owncheckModel = self.env['account.own_check']
        if self.check_supplier_history:
            searchCondition = [('handed_to','=',self.partner_id.id),
                               ('state','not in',['draft'])]
        else:
            searchCondition = [('handed_to', '=', self.partner_id.id),
                               ('payment_date','>=',fields.Date.context_today(self)),
                               ('state','not in',['draft','payed','reject','canceled'])]

        ids = owncheckModel.search(searchCondition)
        check_ids = []
        if ids:
            amount_total = 0.0
            for id in ids:
                amount_total += id.amount
                vals = {'wizard_id': self.id,
                        'check_id': id.id}
                check_supplier_id = self.check_supplier_ids.create(vals).id
                check_ids.append(check_supplier_id)

            if not self.check_supplier_history:
                self.check_supplier_pending = amount_total

        return check_ids

    def compute_lines(self, amls):
        acalModel = self.env['account.current_account.line']
        self.ensure_one()
        wizard = self

        balance = wizard.todays_balance
        date =  datetime.strptime(wizard.from_date, '%Y-%m-%d') - timedelta(days=1)
        ids = []

        if wizard.orden_z_a:
            sequence = len(amls) + 1
            sequence_increment = -1
        else:
            sequence = 1
            sequence_increment = 1

        acal = acalModel.create({'wizard_id': wizard.id,
                                 'name': 'Saldo Anterior',
                                 'balance': balance,
                                 'sequence': sequence,
                                 'date': date,
                                 'date_maturity': date,})
        ids.append(acal.id)

        invoices = {}
        records = {}
        order_ids = []
        for aml in amls:
            if aml.invoice_id and not wizard.by_maturity:
                if aml.invoice_id.id in invoices:
                    records[invoices[aml.invoice_id.id]]['debit'] += aml.debit
                    records[invoices[aml.invoice_id.id]]['credit'] += aml.credit
                    continue
                invoices[aml.invoice_id.id] = aml.id

            order_ids.append(aml.id)
            records[aml.id] = {'id': aml.id,
                               'date': aml.date,
                               'date_maturity': aml.date_maturity,
                               'debit': aml.debit,
                               'credit': aml.credit,
                               'other_currency_id': aml.currency_id.id if aml.currency_id else False,
                               'other_amount': aml.amount_currency,
                               'exchange_rate': abs((aml.debit - aml.credit) / aml.amount_currency) if aml.amount_currency else 0.0,
                               'name': aml.name,
                               'invoice_id': aml.invoice_id or False}

        for order_id in order_ids:
            aml = records[order_id]
            sequence += sequence_increment
            balance += aml['debit'] - aml['credit']
            acal = acalModel.create({'wizard_id': wizard.id,
                                     'aml_id': aml['id'],
                                     'balance': balance,
                                     'sequence': sequence,
                                     'date': aml['date'],
                                     'date_maturity': aml['date_maturity'],
                                     'debit': aml['debit'],
                                     'credit': aml['credit'],
                                     'other_currency_id': aml['other_currency_id'],
                                     'other_amount': aml['other_amount'],
                                     'exchange_rate': aml['exchange_rate'],
                                     'name': aml['name'],
                                     'invoice_id': aml['invoice_id'],
                                     })
            ids.append(acal.id)

        return [(6, 0, ids)]

    def action_refresh_account_current(self):
        self.ensure_one()
        wizard = self
        if not wizard.partner_id:
            return
        if not wizard.currency_id:
            wizard.currency_id = wizard.company_id.currency_id.id
        if not wizard.company_id:
            wizard.company_id = self.env.user.company_id
        if not wizard.from_date:
            wizard.from_date = '1900-01-01'
        if not wizard.til_date:
            wizard.til_date = '2999-12-31'

        wizard.compute_balance()
        amls = wizard.get_move_lines()
        wizard.line_ids = wizard.compute_lines(amls)
        if wizard.customer_ok:
            wizard.check_customer_ids = wizard.get_checks_customer()
        if wizard.supplier_ok:
            wizard.check_supplier_ids = wizard.get_checks_supplier()

class PartnerCurrentAccountLine(models.TransientModel):
    _name = 'account.current_account.line'
    _order = 'sequence asc'

    wizard_id = fields.Many2one('account.current_account', 'Wizard')
    sequence = fields.Integer('Sequence')
    aml_id = fields.Many2one('account.move.line', 'Move line')
    am_id = fields.Many2one('account.move', 'Base move', related='aml_id.move_id')
    registration_date = fields.Date('Registration date')
    date = fields.Date('Date')
    date_maturity = fields.Date('Date Maturity')
    debit = fields.Monetary('Debit')
    credit = fields.Monetary('Credit')
    amount_residual = fields.Monetary('Amount Residual')
    balance = fields.Monetary('Balance')
    currency_id = fields.Many2one('res.currency', 'Currency', related='wizard_id.currency_id')
    other_currency_id = fields.Many2one('res.currency', 'Other currency')
    other_amount = fields.Monetary('Other currency amount', currency_id='other_currency_id')
    exchange_rate = fields.Float('Exchange rate')
    name = fields.Char('Description')
    invoice_id = fields.Many2one('account.invoice', 'Invoice')

    @api.multi
    def action_show(self):
        wizard = self
        if wizard.invoice_id:

            return {
                'name': _("Invoive"),
                'view_mode': 'form',
                'view_type': 'form',
                'res_model': 'account.invoice',
                'res_id': wizard.invoice_id.id,
                'type': 'ir.actions.act_window',
                'target': 'current',
                'nodestroy': True,
                #'flags': {'form': {'action_buttons': False}, 'initial_mode': 'edit'},
            }

    @api.multi
    def action_print(self):
        wizard = self
        return

class CurrentAccountLineCheckCustomer(models.TransientModel):
    _name = 'account.current_account.check_customer'
    _order = 'payment_date'

    wizard_id = fields.Many2one('account.current_account', 'Wizard')
    check_id = fields.Many2one('account.third_party_check', 'Third Party Check')
    image = fields.Binary(' ', related='check_id.image')
    bank_id = fields.Many2one('res.bank','Bank', related='check_id.bank_id')
    bank_branch_id = fields.Many2one('account.bank.branch','Sucursal', related='check_id.bank_branch_id')
    check_number = fields.Char('Nunmber', related='check_id.check_number')
    payment_date = fields.Date('Payment Date', related='check_id.payment_date')
    currency_id = fields.Many2one('res.currency','Currency', related='check_id.currency_id')
    amount = fields.Monetary('Importe', related='check_id.amount')
    cruzado = fields.Boolean('//', related='check_id.cruzado')
    no_a_la_orden =  fields.Boolean('NaO', related='check_id.no_a_la_orden')
    its_own_check = fields.Boolean('Propio', related='check_id.its_own_check')
    issue_date = fields.Date('Issue Date', related='check_id.issue_date')
    valid_from_date = fields.Date('Valid Date', related='check_id.valid_from_date')
    handed_on = fields.Date('Handed On', related='check_id.handed_on')
    handed_to = fields.Many2one('res.partner','Payed on', related='check_id.handed_to')
    name_titular = fields.Char('Titular', related='check_id.name_titular')


class CurrentAccountLineCheckSupplier(models.TransientModel):
    _name = 'account.current_account.check_supplier'
    _order = 'payment_date'

    wizard_id = fields.Many2one('account.current_account', 'Wizard')
    check_id = fields.Many2one('account.own_check', 'Own Check')
    image = fields.Binary('', related='check_id.image')
    bank_id = fields.Char('Bank', related='check_id.bank_id')
    bank_account_id = fields.Char('Cuenta', related='check_id.bank_account_id')
    check_number = fields.Char('Number', related='check_id.check_number')
    payment_date = fields.Date('Payment Date', related='check_id.payment_date')
    currency_id = fields.Char('Currency', related='check_id.currency_id')
    amount = fields.Monetary('Importe', related='check_id.amount')
    issue_date = fields.Date('Issue Date', related='check_id.issue_date')
    valid_from_date = fields.Date('Valid Date', related='check_id.valid_from_date')
    handed_on = fields.Date('Handed On', related='check_id.handed_on')
    payed_on = fields.Date('Payed on', related='check_id.payed_on')

