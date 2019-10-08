# -*- coding: utf-8 -*-

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


class BackgroundJobTest(models.TransientModel):
    _name = "res.background_job_test"
    _description = 'Test class for background jobs'

    job = fields.Many2one("res.background_job", "Job")
    job_completion_rate = fields.Integer(u'Rate', related="job.completion_rate")
    job_current_status = fields.Html(u'Current status', related="job.current_status")
    job_error = fields.Text(u'Error', related="job.error")
    job_state = fields.Selection([
        ('init', 'Initializing'),
        ('started', 'Started'),
        ('ended', 'Ended'),
        ('aborting', 'Aborting ...'),
        ('aborted', 'Aborted'),
    ], u'State', related="job.state")
    state = fields.Selection([
        ('init', 'Initializing'),
        ('running', 'Running'),
        ('aborted', 'Aborted'),
    ], u'State', default='init')
    run_type = fields.Selection([
        ('normal', 'Normal'),
        ('with_error', 'With error'),
        ('with_exception', 'With exception'),
    ], u'State', default='normal')

    def action_refresh(self):
        return {
            'name': _("Test"),
            'view_mode': 'form',
            'view_type': 'form',
            'res_model': 'res.background_job_test',
            'res_id': self.id,
            'target': 'new',
            'type': 'ir.actions.act_window',
        }

    def action_start(self, run_type=None):
        bjt = self[0]

        bjt.state = 'running'
        bjt.run_type = run_type if run_type else 'normal'

        bjt.job = self.env["res.background_job"].create({
            'name': 'Prueba',
            'model': 'res.background_job_test',
            'res_id': bjt.id,
            'method': 'on_job',
            'reference_id': bjt.id,
        })

        return {
            'name': _("Running test"),
            'view_mode': 'form',
            'view_type': 'form',
            'res_model': 'res.background_job_test',
            'res_id': bjt.id,
            'target': 'new',
            'type': 'ir.actions.act_window',
        }

    def action_start_with_error(self):
        bjt = self[0]
        action = bjt.action_start(run_type='with_error')
        action['name'] = _("Running test with error")
        return action

    def action_start_with_exception(self):
        bjt = self[0]
        action = bjt.action_start(run_type='with_exception')
        action['name'] = _("Running test with exception")
        return action

    def action_abort(self):
        bjt = self[0]

        if not bjt.job:
            return True

        bjt.job.try_to_abort(statusMsg=u'Aborted by user')

        bjt.state = 'aborted'
        return {
            'name': _("Aborting test"),
            'view_mode': 'form',
            'view_type': 'form',
            'res_model': 'res.background_job_test',
            'res_id': bjt.id,
            'target': 'new',
            'type': 'ir.actions.act_window',
        }

    def on_job(self, bkJob):
        _logger.info("Starting job")
        count = 0

        bkJob.start('Starting loop to 10')
        wizard = self.env['res.background_job_test'].browse(bkJob.reference_id)

        while count < 10:
            if bkJob.was_aborted():
                bkJob.abort(errorMsg=u'Aborted by user')
                break

            count += 1
            _logger.info("Job count: %d" % count)

            if wizard.run_type == 'with_error' and count == 6:
                bkJob.update_status(errorMsg=u'Error forzado')
                break
            elif wizard.run_type == 'with_exception' and count == 7:
                a = 7/0

            bkJob.update_status(rate=10 * count,
                                statusMsg="Current counter: %d" % count)
            time.sleep(2)

        if count >= 10:
            bkJob.end('<p><b>Everthing ok!</b></p>')
        else:
            bkJob.end('<p><b>Unexpected end!</b></p><p>Try again if you want!</p>')

        _logger.info("Ending job")
