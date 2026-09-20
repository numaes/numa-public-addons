# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

import logging
import time

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# How far the demo job counts
TOTAL_STEPS = 10

# Where each kind of run goes wrong
ERROR_STEP = 6
EXCEPTION_STEP = 7


class ResBackgroundJobTest(models.TransientModel):
    """A wizard that starts a background job, so the widget can be watched working."""
    _name = 'res.background_job_test'
    _description = "Background Job Test"

    job = fields.Many2one('res.background_job', string="Job")
    job_completion_rate = fields.Integer(string="Rate", related='job.completion_rate')
    job_current_status = fields.Text(string="Current status", related='job.current_status')
    job_error = fields.Text(string="Error", related='job.error')
    job_state = fields.Selection(string="Job state", related='job.state')

    state = fields.Selection([
        ('init', "Initializing"),
        ('running', "Running"),
        ('aborted', "Aborted"),
    ], string="State", default='init')
    run_type = fields.Selection([
        ('normal', "Normal"),
        ('with_error', "With error"),
        ('with_exception', "With exception"),
    ], string="Run type", default='normal')
    step_delay = fields.Integer(
        string="Seconds per step", default=2,
        help="How long each step waits, so the progress bar can be watched. Tests set it to 0.")

    def _reopen(self, name):
        """Reopen this wizard, so the form shows what changed."""
        self.ensure_one()
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'res.background_job_test',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_refresh(self):
        return self._reopen(self.env._("Test"))

    def action_start(self, run_type=None):
        self.ensure_one()
        self.write({'state': 'running', 'run_type': run_type or 'normal'})
        # _launch goes through sudo(): ordinary users cannot write the job
        # table, and the owner is carried over on purpose.
        self.job = self.env['res.background_job']._launch(
            self.env._("Background job test"), self, 'on_job')
        return self._reopen(self.env._("Running test"))

    def action_start_with_error(self):
        action = self.action_start(run_type='with_error')
        action['name'] = self.env._("Running test with error")
        return action

    def action_start_with_exception(self):
        action = self.action_start(run_type='with_exception')
        action['name'] = self.env._("Running test with exception")
        return action

    def action_abort(self):
        self.ensure_one()
        if self.job:
            self.job.try_to_abort(statusMsg=self.env._("Aborted by user"))
        self.state = 'aborted'
        return self._reopen(self.env._("Aborting test"))

    def on_job(self, bkJob):
        """Count to ten, reporting progress, the way a real job would.

        This is what ``numa_background_job`` calls in its worker thread. The
        signature is the contract: one argument, the job itself.
        """
        _logger.info("Starting the demonstration job")
        bkJob.start(self.env._("Starting loop to %s", TOTAL_STEPS))
        wizard = self.env['res.background_job_test'].browse(bkJob.reference_id)

        count = 0
        while count < TOTAL_STEPS:
            if bkJob.was_aborted():
                bkJob.abort(errorMsg=self.env._("Aborted by user"))
                return

            count += 1
            if wizard.run_type == 'with_error' and count == ERROR_STEP:
                bkJob.update_status(errorMsg=self.env._("Forced error"))
                break
            if wizard.run_type == 'with_exception' and count == EXCEPTION_STEP:
                raise ZeroDivisionError("forced exception")

            bkJob.update_status(rate=100 * count // TOTAL_STEPS,
                                statusMsg="Current counter: %d" % count)
            if wizard.step_delay:
                time.sleep(wizard.step_delay)

        if count >= TOTAL_STEPS:
            bkJob.end(self.env._("Everything ok!"))
        else:
            bkJob.end(self.env._("Unexpected end! Try again if you want."))
        _logger.info("Ending the demonstration job")
