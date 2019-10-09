# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions
from odoo.tools.translate import _
from datetime import datetime

class Bank(models.Model):
    _inherit = 'res.bank'

    partner_id = fields.Many2one('res.partner', 'Proveedor', ondelete='restrict')
    clearing_propio = fields.Selection([('0', 'Inmediato'),
                                        ('24', '24 horas'),
                                        ('48', '48 horas'),
                                        ('72', '72 horas'),
                                        ('96', '96 horas'),
                                        ('open', 'Abierto'),
                                        ], 'Clearing Propio', default='48')
    image = fields.Binary(string='Logo')
    bank_branch_ids = fields.One2many('account.bank.branch', 'bank_id', 'Sucursales')

    @api.multi
    @api.depends('name', 'bic')
    def name_get(self):
        result = []
        for bank in self:
            name = '[%s] %s' % (bank.bic,bank.name)
            result.append((bank.id, name))

        return result

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        return self.search(['|', ('name', operator, name), ('bic', operator,name)] + args, limit=limit).name_get()

class BankAccount(models.Model):
    _inherit = 'res.partner.bank'

    bank_branch_id = fields.Many2one('account.bank.branch', 'Sucursal', required=True, ondelete='restrict')
    image = fields.Binary(string='Logo', related='bank_id.image', store=True, readonly=True)
    bank_cbu = fields.Char('CBU')
    bank_alias = fields.Char('CBU Alias')
    bank_account_type = fields.Selection([('ca', 'Caja Ahorro'),('cc', 'Cuenta Corriente')], 'Tipo Cuenta', default='cc', required=True)
    name_titular = fields.Char('Nombre Titular')
    cuit_titular = fields.Char('CUIT')
    address_titular = fields.Char('Domicilio')
    bank_account_code = fields.Char(u'Código Cuenta')
    signer_ids = fields.One2many('account.bank.signers', 'bank_account_id', 'Firmantes')
    min_count_of_signers = fields.Integer(u'Nro. Firmantes', default=1)
    cuenta_propia = fields.Boolean('Cuenta Propia?', compute="_cuenta_propia", store=True)
    amount_max_issue = fields.Monetary(u'Máximo a Emitir')
    amount_max_received = fields.Monetary(u'Máximo a Recibir')
    alert = fields.Boolean('Alertar')
    journal_bank_id = fields.Many2one('account.journal','Journal', domain=[('type', '=', 'bank')])
    check_notebook_ids = fields.One2many('account.check.notebook','bank_account_id','Chequeras')
    check_third_party_ids = fields.One2many('account.third_party_check', 'bank_account_id', 'Cheques')
    notes = fields.Text('Notas')

    _sql_constraints = [('bank_branch_id_acc_number_uniq', 'unique(bank_branch_id,acc_number)', u'El Número de Cuenta no debe repetirse para una misma Sucursal Bancaria!')]

    @api.multi
    @api.depends('acc_number','bank_id','bank_branch_id')
    def name_get(self):
        result = []
        for account_partner_bank in self:
            account_type = {'ca':'Caja Ahorro','cc':'Cuenta Corriente'}
            name = '%s %s [%s - %s]' % (account_partner_bank.acc_number,account_partner_bank.bank_id.name,account_type[account_partner_bank.bank_account_type],account_partner_bank.currency_id.name)
            result.append((account_partner_bank.id, name))

        return result

    @api.multi
    @api.depends('partner_id','company_id')
    def _cuenta_propia(self):
        for record in self:
            record.cuenta_propia = False
            if record.partner_id and record.company_id:
                if record.partner_id.id == record.company_id.partner_id.id:
                    record.cuenta_propia = True
        return

    @api.multi
    @api.onchange('bank_id')
    def onchange_bank(self):
        self.bank_branch_id = False
        return

class BankAccountSigners(models.Model):
    _name = 'account.bank.signers'

    name = fields.Many2one(comodel_name='hr.employee', string='Firmante', required=True)
    bank_account_id = fields.Many2one(comodel_name='res.partner.bank', string='Cuenta Bancaria', ondelete='restrict')
    valid_signers_til = fields.Date('Vencimiento')

class BankBranch(models.Model):
    _name = 'account.bank.branch'
    _rec_name = 'branch_name'
    _order = 'branch_code'

    bank_id = fields.Many2one('res.bank', 'Banco', required=True, ondelete='restrict')
    image = fields.Binary(string='Logo', related='bank_id.image', store=True, readonly=True)
    branch_code = fields.Char(u'Código', required=True)
    branch_name = fields.Char('Nombre', required=True)

    branch_address = fields.Many2one('res.partner', 'Domicilio',
                                     domain=[('type', '=', 'contact')])#, ('parent_id', '=', bank_id.partner_id.id)])

    clearing_en_sucursal = fields.Selection([('0', 'Inmediato'),
                                             ('24', '24 horas'),
                                             ('48', '48 horas'),
                                             ('72', '72 horas'),
                                             ('96', '96 horas'),
                                             ('open', 'Abierto'),
                                            ], 'Clearing', default='48')

    notes = fields.Text('Notas')

    _sql_constraints = [('bank_id_branch_code_uniq', 'unique(bank_id,branch_code)', u'El código de Sucursal debe ser único para el Banco!')]

    @api.multi
    @api.depends('branch_name', 'branch_code')
    def name_get(self):
        result = []
        for bank_branch in self:
            name = '[%s] %s' % (bank_branch.branch_code,bank_branch.branch_name)
            result.append((bank_branch.id, name))
        return result

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        newArgs = []
        newArgs.extend(args)
        if args:
            newArgs.extend(['|', ('branch_name', operator, name), ('branch_code', operator, name)])

        return self.search(newArgs + args, limit=limit).name_get()

class BankCheckNotebook(models.Model):
    _name = 'account.check.notebook'
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _order = 'bank_rel,check_type,start_number'

    name = fields.Char('Nombre', readonly=True, states={'draft': [('readonly', False)]})
    image = fields.Binary(string='Image', related='bank_account_id.bank_branch_id.bank_id.image', store=True, readonly=True)
    bank_account_id = fields.Many2one('res.partner.bank', 'Bank account', ondelete='restrict', required=True, readonly=True, states={'draft': [('readonly', False)]})
    bank_rel = fields.Char('Banco', related='bank_account_id.bank_id.name', store=True)
    bank_branch_rel = fields.Char('Sucursal', related='bank_account_id.bank_branch_id.branch_name', store=True)
    start_number = fields.Char('Initial check number', required=True, readonly=True, states={'draft': [('readonly', False)]})
    end_number = fields.Char('Ending check number', required=True, readonly=True, states={'draft': [('readonly', False)]})
    next_to_use = fields.Char('Next check to use', required=True)
    total_qty = fields.Integer('Total quantity of checks', compute='_total_qty') #compute=lambda cn: cn.end_number - cn.start_number + 1)
    available_qty = fields.Integer('Available quantity of checks', compute='_available_qty') #compute=lambda cn: cn.end_number - cn.next_to_use + 1)
    valid_from = fields.Date('Valid from', readonly=True, states={'draft': [('readonly', False)]})
    last_check_on = fields.Date('Last check date')
    state = fields.Selection([('draft', 'Draft'),
                              ('in_use', 'In use'),
                              ('stand_by', 'Stand by'),
                              ('fully_used', 'Fully used')], 'State', default='draft')
    alert_on = fields.Integer('Alert when', default=10)
    check_type = fields.Selection([('on_date', 'On emition date'),
                                   ('deferred', 'Deferred'),
                                  ], 'Check type', default='deferred', required=True, readonly=True, states={'draft': [('readonly', False)]})
    printed_form_type = fields.Selection([('notebook', 'Check notebook'),
                                          ('printer', 'To be used on printer')])
    check_ids = fields.One2many('account.own_check', 'notebook_id', 'Cheques')
    notes = fields.Text('Notes')

    @api.multi
    @api.depends('start_number','end_number')
    def _total_qty(self):
        if self.start_number and self.end_number:
            self.total_qty = float(self.end_number) - float(self.start_number) + 1
        return

    @api.multi
    @api.depends('next_to_use','end_number')
    def _available_qty(self):
        if self.next_to_use and self.end_number:
            self.available_qty = float(self.end_number) - float(self.next_to_use) + 1
        return

    @api.multi
    @api.onchange('bank_account_id','start_number','end_number')
    def onchange_name(self):
        if self.start_number and self.end_number:
            if float(self.start_number) >= float(self.end_number):
                raise exceptions.Warning(_(u'Número Inicial debe ser menor que Número Final'))
            if self.bank_account_id:
                self.name = '%s [%s - %s]' % (self.bank_account_id.acc_number,self.start_number,self.end_number)
                self.next_to_use = self.start_number
        return

    @api.multi
    def action_draft(self):
        self.write({'state': 'draft'})
        return

    @api.multi
    def action_in_use(self):
        self.write({'state':'in_use'})
        return

    @api.multi
    def action_stand_by(self):
        self.write({'state':'stand_by'})
        return

    @api.multi
    def action_fully_used(self):
        self.write({'state': 'fully_used'})
        return

class ThirdPartyCheck(models.Model):
    _name = 'account.third_party_check'
    _rec_name = 'check_number'
    _order = 'payment_date'

    check_number = fields.Char('Check number', readonly=True, states={'draft': [('readonly', False)]})
    currency_id = fields.Many2one('res.currency', 'Currency',
                              related='bank_account_id.currency_id',
                              readonly=True,
                              store=True)
    bank_account_id = fields.Many2one('res.partner.bank', 'Bank account', readonly=True, states={'draft': [('readonly', False)]})
    bank_id = fields.Many2one('res.bank', 'Bank', related='bank_account_id.bank_id', readonly=True, store=True)
    bank_branch_id = fields.Many2one('account.bank.branch', 'Bank branch', related='bank_account_id.bank_branch_id', readonly=True, store=True)
    name_titular = fields.Char('Nombre Titular', related='bank_account_id.name_titular')
    cuit_titular = fields.Char('CUIT', related='bank_account_id.cuit_titular')
    address_titular = fields.Char('Domicilio', related='bank_account_id.address_titular')
    bank_account_code = fields.Char(u'Código Cuenta', related='bank_account_id.bank_account_code')

    micr = fields.Char('MICR')
    front_image = fields.Binary('Front image')
    back_image = fields.Binary('Back image')

    amount = fields.Monetary('Amount', readonly=True, states={'draft': [('readonly', False)]})

    issue_date = fields.Date('Issue date', readonly=True, states={'draft': [('readonly', False)]}, default = datetime.today())
    valid_from_date = fields.Date('Valid from', readonly=True, states={'draft': [('readonly', False)]})
    payment_date = fields.Date('Payment date', readonly=True, states={'draft': [('readonly', False)]})

    image = fields.Binary(string='Image', related='bank_account_id.bank_branch_id.bank_id.image', store=True, readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('receivable', 'Receivable'),

        ('custody', 'In custody'),
        ('discounted', 'Discounted'),

        ('receivable2', 'Not to Pay'),

        ('warrant', 'Warrant'),

        ('withdraw', 'Depositado'),
        ('to_be_fixed', 'To be fixed'),
        ('handed_out', 'Handed out'),
        ('rejected', 'Rejected'),
        ('canceled', 'Canceled'),
    ], 'State', default='draft')

    received_from = fields.Many2one('res.partner', 'Received from', readonly=True, states={'draft': [('readonly', False)]})
    received_on = fields.Date('Received on', default = datetime.today())
    received_move_line_id = fields.Many2one('account.move.line', 'Received move line',
                                            readonly=True)

    to_be_fixed_reason = fields.Text('To be fixed reason')
    to_be_fixed_on = fields.Date('Handed out to be fixed on')
    to_be_fixed_received_on = fields.Date('Received back on')

    handed_to = fields.Many2one('res.partner', 'Handed out to',
                                readonly=True, states={'draft': [('readonly', False)],
                                                       'receivable2': [('readonly', False)]})
    handed_on = fields.Date('Handed on')
    handed_move_line_id = fields.Many2one('account.move.line', 'Handed out move line',
                                            readonly=True)
    #state = fields.Selection([
       # ('no_a_la_orden', 'No a la orden'),
       # ('issued', 'Issued'),
       # ('payed', 'Payed'),
       # ('rejected', 'Rejected'),
       # ('canceled', 'Canceled'),
    #], 'State', readonly=True)

    cruzado = fields.Boolean(u'Cruzado')
    no_a_la_orden = fields.Boolean(u'No a la orden')

    custody_bank_account_id = fields.Many2one('res.partner.bank', 'Custody bank account', readonly = True, states = {'custody': [('readonly', False)]})

    its_own_check = fields.Boolean('Is it own check?')

    rejected_on = fields.Date('Rejected on', readonly=True)
    rejected_move_line_id = fields.Many2one('account.move.line', 'Rejected move line', readonly=True)

    notes = fields.Text('Notes')

    @api.multi
    @api.onchange('micr')
    def onchange_micr(self):
        if self.micr:
            account_third_party_check_obj = self.env['account.third_party_check']
            mic_parse = self.micr.replace(';','').replace(':','')
            bank_code = mic_parse[:3]
            bank_branch_code = mic_parse[3:6]
            cp = mic_parse[6:10]
            check_number = mic_parse[10:18]
            bank_account = mic_parse[18:29]
            if not(bank_code and bank_branch_code and cp and check_number and bank_account):
                raise exceptions.Warning(_(u'MICR Incorrecto'))

            check_number = mic_parse[10:18]
            check = account_third_party_check_obj.search([('bank_account_id.bank_account_code','=',bank_account),
                                                          ('bank_account_id.bank_id.bic','=',bank_code),
                                                          ('check_number','=',check_number),
                                                          ('state','in',['draft','receivable','receivable2','warrant'])])
            if check:
                raise exceptions.Warning(_(u'Este cheque ya se encuentra registrado'))
            else:
                res_partner_bank_obj = self.env['res.partner.bank']
                res_partner_bank = res_partner_bank_obj.search([('bank_id.bic','=',bank_code),
                                                                ('bank_branch_id.branch_code','=',bank_branch_code),
                                                                ('bank_account_code','=',bank_account)])
                if res_partner_bank:
                    self.bank_account_id = res_partner_bank.id
                else:
                    self.bank_account_code = bank_account
                self.check_number = check_number

        return

    @api.multi
    def action_draft(self):
        self.write({'state': 'draft'})
        return

    @api.multi
    def action_receivable(self):
        self.write({'state':'receivable'})
        return

    @api.multi
    def action_receivable2(self):
        self.write({'state':'receivable2'})
        return


    @api.multi
    def action_custody(self):
        self.write({'state':'custody'})
        return

    @api.multi
    def action_discounted(self):
        self.write({'state': 'discounted'})
        return

    @api.multi
    def action_warrant(self):
        self.write({'state': 'warrant'})
        return

    @api.multi
    def action_withdraw(self):
        self.write({'state': 'withdraw'})
        return

    @api.multi
    def action_to_be_fixed(self):
        self.write({'state': 'to_be_fixed'})
        return

    @api.multi
    def action_handed_out(self):
        self.write({'state': 'handed_out'})
        return


    @api.multi
    def action_rejected(self):
        self.write({'state': 'rejected'})
        return

    @api.multi
    def action_canceled(self):
        self.write({'state': 'canceled'})
        return


class OwnCheck(models.Model):
    _name = 'account.own_check'
    _rec_name = 'notebook_id'
    _order = 'payment_date'

    notebook_id = fields.Many2one('account.check.notebook', 'Check notebook',
                                  required=True,
                                  readonly=True, states={'draft': [('readonly', False),('required',False)]})
    check_number = fields.Char('Check number',
                                  required=True,
                                  readonly=True, states={'draft': [('readonly', False),('required',False)]})
    currency_id = fields.Char('Currency',
                              related='notebook_id.bank_account_id.currency_id.name',
                              readonly=True,
                              store=True)
    bank_account_id = fields.Char('Bank account',
                                  related='notebook_id.bank_account_id.acc_number',
                                  readonly=True,
                                  store=True)
    bank_id = fields.Char('Bank',
                          related='notebook_id.bank_account_id.bank_id.name',
                          readonly=True,
                          store=True)

    image = fields.Binary(string='Image', related='notebook_id.bank_account_id.bank_branch_id.bank_id.image', store=True, readonly=True)

    micr = fields.Char('MICR')

    amount = fields.Monetary('Amount',
                             required=True,
                             readonly=True, states={'draft': [('readonly', False),('required',False)]})

    pay_to = fields.Char('Pay to', readonly=True, states={'draft': [('readonly', False)]})
    front_image = fields.Binary('Front image')
    back_image = fields.Binary('Back image')
    signers = fields.Many2many('hr.employee', string='Signers')

    issue_date = fields.Date('Issue date', readonly=True, states={'draft': [('readonly', False)]}, default = datetime.today())
    valid_from_date = fields.Date('Valid from', readonly=True, states={'draft': [('readonly', False)]}, default = datetime.today())
    payment_date = fields.Date('Payment date', readonly=True, states={'draft': [('readonly', False)]})

    state = fields.Selection([
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('delivered', 'Delivered'),
        ('payed', 'Payed'),
        ('rejected', 'Rejected'),
        ('canceled', 'Canceled'),
    ], 'State', default="draft", readonly=True)

    handed_to = fields.Many2one('res.partner', 'Handed out to', readonly=True)
    handed_on = fields.Date('Handed out on', readonly=True)
    handed_move_line_id = fields.Many2one('account.move.line', 'Handed out move line', readonly=True)

    rejected_on = fields.Date('Rejected on', readonly=True)
    rejected_move_line_id = fields.Many2one('account.move.line', 'Rejected move line', readonly=True)

    payed_on = fields.Date('Payed on', readonly=True)
    payed_move_line_id = fields.Many2one('account.move.line', 'Payed move line', readonly=True)

    notes = fields.Text('Notes')

    _sql_constraints = [('notebook_id_check_number_uniq', 'unique(notebook_id,check_number)',u'El Cheque ya se encuentra registrado!')]

    @api.multi
    @api.onchange('micr')
    def onchange_micr(self):
        if self.micr:
            account_check_notebook_obj = self.env['account.check.notebook']
            mic_parse = self.micr.replace(';','').replace(':','')
            bank_code = mic_parse[:3]
            bank_branch_code = mic_parse[3:6]
            cp = mic_parse[6:10]
            check_number = mic_parse[10:18]
            bank_account = mic_parse[18:29]
            if not(bank_code and bank_branch_code and cp and check_number and bank_account):
                raise exceptions.Warning(_(u'MICR Incorrecto'))

            check = account_check_notebook_obj.search([('bank_account_id.bank_id.bic','=',bank_code),
                                                       ('bank_account_id.bank_branch_id.branch_code','=',bank_branch_code),
                                                       ('start_number','<=', check_number),
                                                       ('end_number','>=', check_number),
                                                       ('state','=','in_use')])
            if check:
                account_own_check_obj = self.env['account.own_check']
                if account_own_check_obj.search([('notebook_id','=',check.id),('check_number','=',check_number)]):
                    raise exceptions.Warning(_(u'Este cheque ya se encuentra registrado'))
                self.check_number = check_number
                self.notebook_id = check.id
                self.bank_id = check.bank_account_id.bank_id.name
                self.bank_account_id = bank_account
            else:
                self.check_number = 0
                self.notebook_id = False
                raise exceptions.Warning(_(u'No se encontró chequera en uso para este cheque'))
        return


    @api.multi
    def action_draft(self):
        self.write({'state': 'draft'})
        return

    @api.multi
    def action_issued(self):
        self.write({'state':'issued'})
        return

    @api.multi
    def action_delivered(self):
        self.write({'state':'delivered'})
        return

    @api.multi
    def action_payed(self):
        self.write({'state': 'payed'})
        return

    @api.multi
    def action_rejected(self):
        self.write({'state': 'rejected'})
        return

    @api.multi
    def action_canceled(self):
        self.write({'state': 'canceled'})
        return

    @api.multi
    def action_availability(self):
        return
