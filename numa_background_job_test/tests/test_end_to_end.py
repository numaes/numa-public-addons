# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""A whole background job, from the wizard button to the final state.

The worker is called here rather than started in a thread: a thread would not
share the test's cursor, and the one line that starts it is covered by the
suite of ``numa_background_job``. Everything the worker itself does is real.
"""

import json
from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon
from odoo.addons.numa_background_job import worker
from odoo.tools import mute_logger

WORKER_LOGGER = 'odoo.addons.numa_background_job.worker'


class TestEndToEnd(BaseCommon):
    _test_user_groups = ('base.group_user',)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enterClassContext(cls.registry_test_mode())

    def _start(self, run_type='normal'):
        """Press the wizard's button and return the job it created."""
        wizard = self.env['res.background_job_test'].create({'step_delay': 0})
        started = []
        with patch.object(worker, 'start_worker',
                          lambda *args, **kwargs: started.append(args)):
            wizard.action_start(run_type=run_type)
            for callback in list(self.env.cr.postcommit._funcs):
                callback()
            self.env.cr.postcommit._funcs.clear()
        self.assertEqual(len(started), 1, "the worker is asked for exactly once")
        return wizard, wizard.job, started[0]

    def _run(self, arguments):
        worker.run_job(*arguments)

    def test_an_employee_can_start_a_job(self):
        wizard, job, _arguments = self._start()

        self.assertTrue(job)
        self.assertEqual(job.user_id, self.env.user, "the job belongs to whoever asked")
        self.assertEqual(job.model, 'res.background_job_test')
        self.assertEqual(job.method, 'on_job')
        self.assertEqual(job.state, 'init')
        self.assertEqual(wizard.state, 'running')

    def test_a_job_that_finishes(self):
        _wizard, job, arguments = self._start()

        self._run(arguments)

        self.assertEqual(job.state, 'ended')
        self.assertEqual(job.completion_rate, 100)
        self.assertIn("Everything ok", job.current_status)
        self.assertFalse(job.error)

    def test_a_job_that_reports_an_error(self):
        _wizard, job, arguments = self._start(run_type='with_error')

        self._run(arguments)

        self.assertEqual(job.state, 'ended', "the job finished, it just went badly")
        self.assertIn("Forced error", job.error)
        self.assertLess(job.completion_rate, 100)

    @mute_logger(WORKER_LOGGER)
    def test_a_job_that_raises_is_aborted_with_its_traceback(self):
        _wizard, job, arguments = self._start(run_type='with_exception')

        self._run(arguments)

        self.assertEqual(job.state, 'aborted')
        self.assertIn('ZeroDivisionError', job.error)
        self.assertIn('Traceback', job.error, "the traceback is kept for whoever looks")

    @mute_logger(WORKER_LOGGER)
    def test_a_job_whose_target_is_gone_is_aborted_not_run(self):
        _wizard, job, arguments = self._start()
        job.sudo().write({'method': 'no_such_method'})

        self._run(arguments)

        self.assertEqual(job.state, 'aborted')
        self.assertIn('does not exist', job.error)

    def test_a_job_asked_to_stop_does(self):
        _wizard, job, arguments = self._start()

        # The abort arrives between two steps, which is where the job looks
        # for it: was_aborted() is the whole contract.
        with patch.object(type(job), 'was_aborted', lambda self: True):
            self._run(arguments)

        self.assertEqual(job.state, 'aborted')
        self.assertLess(job.completion_rate, 100)

    def test_a_job_called_off_before_the_worker_takes_it_is_left_alone(self):
        _wizard, job, arguments = self._start()
        job.try_to_abort("Changed my mind")

        self._run(arguments)

        self.assertEqual(job.state, 'aborting', "the worker did not run what was called off")
        self.assertEqual(job.completion_rate, 0)

    def test_the_owner_is_told_how_it_went(self):
        _wizard, job, arguments = self._start()
        before = self.env['bus.bus'].sudo().search([], order='id desc', limit=1).id or 0

        self._run(arguments)

        self.env.cr.flush()
        rows = self.env['bus.bus'].sudo().search([('id', '>', before)])
        channels = [json.loads(row.channel) for row in rows]
        self.assertIn([self.env.cr.dbname, 'res.users', self.env.uid], channels,
                      "progress goes to the owner's own channel")
        self.assertTrue(len(rows) > 5, "progress is reported as it goes, not only at the end")
