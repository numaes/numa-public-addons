# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.tools.translate import _
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta

import logging


class account_fiscalyears(models.Model):
    _name = 'account.fiscalyears'
    _order = 'company_id, date_start'

    name = fields.Char('Fiscal Year', size=64, required=True)
    code = fields.Char('Code', size=6, required=True)
    company_id = fields.Many2one('res.company', 'Company', required=True,
                                 default=lambda self: self.env['res.company']._company_default_get(
                                     'account.fiscalyears'))
    company_image = fields.Binary(string='Company Image', related='company_id.logo', readonly=True)
    date_start = fields.Date('Start Date', required=True)
    date_end = fields.Date('End Date', required=True)
    period_ids = fields.One2many('account.period', 'fiscalyear_id', 'Periods', default=False)
    state = fields.Selection([('draft', 'Draft'), ('open', 'Open'), ('process', 'Process'), ('close', 'Close')],
                             'State', readonly=True, default='open')
    note = fields.Text('Notes')

    @api.onchange('date_start')
    def onchange_date_start(self):
        if self.date_start:
            de = datetime.strptime(self.date_start, '%Y-%m-%d') + relativedelta(years=1, days=-1)
            self.date_end = datetime.strftime(de, '%Y-%m-%d')

    @api.onchange('date_end')
    def onchange_date_end(self):
        if self.date_start and self.date_end:
            if self.date_start > self.date_end:
                self.date_end = False

    @api.multi
    def action_create_period_mounth(self):
        self.ensure_one()
        if not self.period_ids:
            period_obj = self.env['account.period']
            ds = datetime.strptime(self.date_start, '%Y-%m-%d')
            period_obj.create({'name': "%s %s" % (_('Opening'), ds.strftime('%Y')),
                               'code': ds.strftime('%Y/00'),
                               'special': True,
                               'date_start': ds,
                               'date_end': ds,
                               'fiscalyear_id': self.id,
                               'state': 'open'})

            while ds.strftime('%Y-%m-%d') < self.date_end:
                de = ds + relativedelta(months=1, days=-1)
                if de.strftime('%Y-%m-%d') > self.date_end:
                    de = datetime.strftime(self.date_end, '%Y-%m-%d')
                period_obj.create({'name': ds.strftime('%Y-%m'),
                                   'code': ds.strftime('%Y-%m'),
                                   'special': False,
                                   'date_start': ds.strftime('%Y-%m-%d'),
                                   'date_end': de.strftime('%Y-%m-%d'),
                                   'fiscalyear_id': self.id})
                ds = ds + relativedelta(months=1)
        return True

    @api.multi
    def action_create_period_trimester(self):
        self.ensure_one()
        if not self.period_ids:
            period_obj = self.env['account.period']
            ds = datetime.strptime(self.date_start, '%Y-%m-%d')
            period_obj.create({'name': "%s %s" % (_('Opening Period'), ds.strftime('%Y')),
                               'code': ds.strftime('%Y/00'),
                               'special': True,
                               'date_start': ds,
                               'date_end': ds,
                               'fiscalyear_id': self.id,
                               'state': 'open'})

            while ds.strftime('%Y-%m-%d') < self.date_end:
                de = ds + relativedelta(months=3, days=-1)
                if de.strftime('%Y-%m-%d') > self.date_end:
                    de = datetime.strftime(self.date_end, '%Y-%m-%d')

                period_obj.create({'name': ds.strftime('%Y-%m'),
                                   'code': ds.strftime('%Y-%m'),
                                   'special': False,
                                   'date_start': ds.strftime('%Y-%m-%d'),
                                   'date_end': de.strftime('%Y-%m-%d'),
                                   'fiscalyear_id': self.id})
                ds = ds + relativedelta(months=3)
        return True

    @api.multi
    def action_to_draft(self):
        self.write({'state': 'draft'})
        return

    @api.multi
    def action_open(self):
        self.write({'state': 'open'})
        return

    @api.multi
    def action_process(self):
        self.write({'state': 'process'})
        return

    @api.multi
    def action_close(self):
        self.write({'state': 'close'})
        return

class account_period(models.Model):
    _name = 'account.period'
    _order = 'company_id, date_end'

    name = fields.Char('Name', size=64, required=True)
    code = fields.Char('Code', size=12, required=True)
    special = fields.Boolean('Opening Period', readonly=True)
    company_id = fields.Many2one(string='Company', related='fiscalyear_id.company_id', readonly=True)
    company_image = fields.Binary(string='Company Image', related='fiscalyear_id.company_id.logo', readonly=True)
    date_start = fields.Date('Start Date', required=True, states={'done': [('readonly', '=', True)]}, readonly=True)
    date_end = fields.Date('End Date', required=True, states={'done': [('readonly', '=', True)]}, readonly=True)
    fiscalyear_id = fields.Many2one('account.fiscalyears', 'Fiscal Year', states={'done': [('readonly', '=', True)]},
                                    readonly=True, ondelete='restrict')
    state = fields.Selection([('draft', 'Draft'), ('open', 'Open'), ('process', 'Process'), ('close', 'Close')],
                             'State', readonly=True, default='draft')
    note = fields.Text('Notes')

    @api.multi
    def name_get(self):
        res = []
        for period in self:
            res.append([period.id, "%s - %s" % (period.name, period.company_id.name)])

        return res

    @api.multi
    def action_to_draft(self):
        self.write({'state': 'draft'})
        return

    @api.multi
    def action_open(self):
        for line in self:
            line.write({'state': 'open'})
        return

    @api.multi
    def action_process(self):
        self.write({'state': 'process'})
        return

    @api.multi
    def action_close(self):
        self.write({'state': 'close'})
        return