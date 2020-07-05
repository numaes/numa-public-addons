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


class AcumarAcuerdo(models.Model):
    _name = 'acumar.acuerdo'
    _description = 'Acuerdo con ACUMAR'
    _order = 'name'

    @api.model
    def get_default_sequence(self):
        self.env.cr.execute('SELECT max(sequence) FROM acumar_acuerdo')
        result = self.env.cr.fetchall()
        if result:
            return result[0][0] + 1
        else:
            return 1

    name = fields.Char('Título', required=True,
                       readonly=True, states={'draft': [('readonly', False)]})
    sequence = fields.Integer('Nro. orden', default=get_default_sequence, required=True,
                              readonly=True, states={'draft': [('readonly', False)]})
    tematica_id = fields.Many2one('acumar.tematica', 'Temática',
                                  readonly=True, states={'draft': [('readonly', False)]})

    state = fields.Selection(
        [('draft', 'Borrador'),
         ('sd', 'S/D'),
         ('running', 'En ejecución'),
         ('terminated', 'Terminado'),
         ('canceled', 'Cancelado')],
        'Estado',
        default='draft',
        copy=False, index=True, tracking=3,
        readonly=True,
    )

    suscription_date = fields.Date('Fecha de suscripción',
                                   readonly=True, states={'draft': [('readonly', False)]})
    partners = fields.Many2one('acumar.contraparte', string='Contrapartes',
                               readonly=True, states={'draft': [('readonly', False)]})
    goal = fields.Text('Objeto',
                       readonly=True, states={'draft': [('readonly', False)]})
    agreed_amount = fields.Monetary('Monto convenido')
    company_id = fields.Many2one('res.company', 'Ente principal', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', 'Moneda', related='company_id.currency_id', readonly=True)
    due_date = fields.Date('Fecha de vencimiento')
    to_be_checked = fields.Boolean('A revisar?')
    automatic_renovation = fields.Boolean('Renovación automática?',
                                          readonly=True, states={'draft': [('readonly', False)]})
    current_situation = fields.Char('Estado actual',
                                    compute='get_current_situation')
    renovation_description = fields.Text('Vigencia',
                                         readonly=True,
                                         states={'draft': [('readonly', False)],
                                                 'running': [('readonly', False)]})
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
                elif self.suscription_date > today:
                    self.current_situation = 'Todavía no vigente'
                else:
                    self.current_situation = ''

    @api.onchange('suscription_date')
    def onchange_suscription_date(self):
        if not self.due_date or self.due_date < self.suscription_date:
            self.due_date = self.suscription_date + timedelta(days=365)

    @api.onchange('due_date')
    def onchange_due_date(self):
        if self.suscription_date and self.due_date < self.suscription_date:
            raise UserWarning(
                _('La fecha de vencimiento no puede ser anterior a la fecha de suscripción.\nPor favor revisar')
            )

    def action_recompute_state(self):
        today = fields.Date.context_today(self)

        for agreement in self:
            if agreement.state == 'running' and \
                agreement.suscription_date and agreement.due_date and not agreement.automatic_renovation and \
                    agreement.due_date < today:
                agreement.state = 'terminated'
            elif agreement.state == 'draft' and \
                    agreement.suscription_date and agreement.suscription_date >= today:
                agreement.state = 'running'

    def action_cancel(self):
        for agreement in self:
            if agreement.state in ('draft', 'running'):
                agreement.state = 'canceled'

