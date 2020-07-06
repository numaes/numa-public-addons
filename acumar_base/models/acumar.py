# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
import odoo
from odoo import models, fields, api, modules, SUPERUSER_ID

from odoo.tools.translate import _

import threading
import datetime
import time

import sys
import traceback

import logging

_logger = logging.getLogger(__name__)


class AcumarTematica(models.Model):
    _name = 'acumar.tematica'
    _description = 'Temática'

    name = fields.Char('Nombre', required=True)
    description = fields.Text('Descripción')


class AcumarContraparte(models.Model):
    _name = 'acumar.contraparte'
    _description = 'Contraparte'

    _inherits = {
        'res.partner': 'partner_id',
    }

    partner_id = fields.Many2one('res.partner', 'Empresa', required=True, ondelete='cascade')
    acuerdos = fields.Many2many('acumar.acuerdo', 'acuerdo_contraparte', 'contraparte_id', 'acuerdo_id',
                                string='Acuerdos')


class AcumarAcuerdo(models.Model):
    _name = 'acumar.acuerdo'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'utm.mixin']
    _description = 'Acuerdo con ACUMAR'
    _order = 'name'

    @api.model
    def get_default_sequence(self):
        self.env.cr.execute('SELECT max(sequence) FROM acumar_acuerdo')
        result = self.env.cr.fetchall()
        if result and result[0][0]:
            return result[0][0] + 1
        else:
            return 1

    name = fields.Char('Título', required=True)
    sequence = fields.Integer('Nro. orden', default=get_default_sequence, required=True)
    tematica_id = fields.Many2one('acumar.tematica', 'Temática')

    state = fields.Selection(
        [('draft', 'Borrador'),
         ('sd', 'S/D'),
         ('running', 'En ejecución'),
         ('to_extend', 'Por terminar'),
         ('terminated', 'Terminado'),
         ('canceled', 'Cancelado')],
        'Estado',
        default='draft',
        copy=False, index=True, tracking=3,
        readonly=True,
    )

    suscription_date = fields.Date('Fecha de suscripción')
    partners = fields.Many2many('acumar.contraparte', 'acuerdo_contraparte', 'acuerdo_id', 'contraparte_id',
                                string='Contrapartes')
    goal = fields.Text('Objeto')
    agreed_amount = fields.Monetary('Monto convenido')
    company_id = fields.Many2one('res.company', 'Ente principal', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', 'Moneda', related='company_id.currency_id', readonly=True)
    due_date = fields.Date('Fecha de vencimiento')
    to_be_checked = fields.Boolean('A revisar?')
    automatic_renovation = fields.Boolean('Renovación automática?')
    current_situation = fields.Char('Estado actual',
                                    compute='get_current_situation')
    renovation_description = fields.Text('Vigencia')
    dc_approval = fields.Text('Aprobación CD')
    order_year = fields.Char('Orden/Año')
    expediente = fields.Char('Expediente')
    alert = fields.Text('Alerta')
    notes_1 = fields.Text('Obs1')
    notes_2 = fields.Text('Obs2')

    def get_current_situation(self):
        today = fields.Date.context_today(self)
        for agreement in self:
            if self.suscription_date and \
               self.suscription_date <= today and \
               agreement.automatic_renovation:
                self.current_situation = 'Renovación automática'
            else:
                if self.due_date and not self.to_be_checked:
                    days_before_due = today - self.due_date
                    if days_before_due.days < 0:
                        self.current_situation = 'Vencido'
                    else:
                        self.current_situation = 'No vencido'
                elif self.to_be_checked:
                    self.current_situation = 'A revisar'
                elif self.suscription_date and self.suscription_date > today:
                    self.current_situation = 'Todavía no vigente'
                else:
                    self.current_situation = ''

    @api.onchange('suscription_date')
    def onchange_suscription_date(self):
        if self.suscription_date and (not self.due_date or self.due_date < self.suscription_date):
            self.due_date = self.suscription_date + timedelta(days=365)

    @api.onchange('due_date')
    def onchange_due_date(self):
        if self.suscription_date and self.due_date and \
                self.due_date < self.suscription_date:
            raise UserWarning(
                _('La fecha de vencimiento no puede ser anterior a la fecha de suscripción.\nPor favor revisar')
            )

    @api.onchange('state', 'suscription_date', 'automatic_renovation', 'due_date')
    def action_recompute_state(self):
        today = fields.Date.context_today(self)

        for agreement in self:
            if agreement.state != 'canceled':
                if agreement.suscription_date:
                    if agreement.automatic_renovation:
                        agreement.state = 'running'
                    elif not agreement.due_date:
                        agreement.state = 'sd'
                    else:
                        if agreement.suscription_date > today:
                            agreement.state = 'draft'
                        else:
                            days_to_finish = (today - agreement.due_date).days
                            if days_to_finish > 0:
                                agreement.state = 'terminated'
                            elif days_to_finish > -90:
                                agreement.state = 'to_extend'
                            else:
                                agreement.state = 'running'
                else:
                    agreement.state = 'draft'

    def write(self, values):
        ret_value = super().write(values)
        if 'suscription_state' in values or \
            'due_date' in values or \
            'automatic_renovation' in values:
            self.action_recompute_state()
        return ret_value

    def action_cancel(self):
        for agreement in self:
            if agreement.state != 'canceled':
                agreement.state = 'canceled'

    def recompute_all(self):
        self.search([]).action_recompute_state()
