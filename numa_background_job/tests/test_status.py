# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""How a job moves between states, and who is told about it."""

from odoo import fields

from .common import BackgroundJobCommon
from ..models.res_background_job import (
    DEFAULT_RETENTION_DAYS, NOTIFICATION_TYPE, RETENTION_DAYS_PARAM,
)


class TestCreation(BackgroundJobCommon):

    def test_a_new_job_starts_initializing(self):
        job = self.make_job()

        self.assertEqual(job.state, 'init')
        self.assertTrue(job.initialized_on)
        self.assertFalse(job.started_on)
        self.assertFalse(job.ended_on)

    def test_a_requested_state_is_ignored(self):
        job = self.make_job(state='ended')

        self.assertEqual(job.state, 'init', "a job cannot be born finished")

    def test_several_jobs_are_created_at_once(self):
        with self.collect_threads():
            jobs = self.env['res.background_job'].create([
                {'name': "First", 'model': 'res.partner', 'res_id': self.partner.id,
                 'method': 'write', 'user_id': self.env.uid},
                {'name': "Second", 'model': 'res.partner', 'res_id': self.partner.id,
                 'method': 'write', 'user_id': self.env.uid},
            ])

        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(jobs.mapped('initialized_on')))

    def test_the_worker_starts_only_after_the_commit(self):
        with self.collect_threads() as started:
            job = self.env['res.background_job'].create({
                'name': "Deferred", 'model': 'res.partner', 'res_id': self.partner.id,
                'method': 'write', 'user_id': self.env.uid,
            })
            self.assertEqual(started, [], "nothing runs before the transaction commits")
            self.run_postcommit()

        self.assertEqual(len(started), 1)
        db_name, uid, name, job_id, _context = started[0]
        self.assertEqual(db_name, self.env.cr.dbname)
        self.assertEqual(uid, self.env.uid)
        self.assertEqual(job_id, job.id)
        self.assertEqual(name, "Deferred")

    def test_launch_keeps_the_real_owner(self):
        # _launch creates through sudo(), so the owner has to be passed on
        # purpose or the job would belong to OdooBot.
        job = self.env['res.background_job']._launch("Launched", self.partner, 'write')

        self.assertEqual(job.user_id, self.env.user)
        self.assertEqual(job.model, 'res.partner')
        self.assertEqual(job.res_id, self.partner.id)
        self.assertEqual(job.reference_id, self.partner.id)


class TestTransitions(BackgroundJobCommon):

    def test_starting_a_job(self):
        job = self.make_job()

        job.start("Off we go")

        self.assertEqual(job.state, 'started')
        self.assertTrue(job.started_on)
        self.assertEqual(job.current_status, "Off we go")

    def test_a_job_is_started_once(self):
        job = self.make_job()
        job.start()
        first_start = job.started_on

        job.start("Again")

        self.assertEqual(job.started_on, first_start, "only a job in init can start")

    def test_reporting_progress(self):
        job = self.make_job()
        job.start()

        job.update_status(rate=42, statusMsg="Half way")

        self.assertEqual(job.completion_rate, 42)
        self.assertEqual(job.current_status, "Half way")

    def test_progress_is_only_reported_while_running(self):
        job = self.make_job()

        job.update_status(rate=42)

        self.assertEqual(job.completion_rate, 0, "a job that has not started reports nothing")

    def test_ending_a_job(self):
        job = self.make_job()
        job.start()

        job.end("All done")

        self.assertEqual(job.state, 'ended')
        self.assertTrue(job.ended_on)
        self.assertEqual(job.current_status, "All done")

    def test_a_finished_job_does_not_end_twice(self):
        job = self.make_job()
        job.start()
        job.end("First")

        job.end("Second")

        self.assertEqual(job.current_status, "First")

    def test_asking_a_job_to_stop(self):
        job = self.make_job()
        job.start()

        job.try_to_abort("Enough")

        self.assertEqual(job.state, 'aborting')
        self.assertEqual(job.current_status, "Enough")

    def test_a_job_that_stopped(self):
        job = self.make_job()
        job.start()
        job.try_to_abort()

        job.abort(errorMsg="Cancelled by the user")

        self.assertEqual(job.state, 'aborted')
        self.assertEqual(job.error, "Cancelled by the user")

    def test_was_aborted_tells_a_running_job_to_stop(self):
        job = self.make_job()
        job.start()
        self.assertFalse(job.was_aborted())

        job.try_to_abort()

        self.assertTrue(job.was_aborted())

    def test_a_finished_job_reads_as_aborted_by_was_aborted(self):
        job = self.make_job()
        job.start()
        job.end()

        self.assertTrue(job.was_aborted(), "there is no point carrying on either way")

    def test_get_current_state_reads_the_database(self):
        job = self.make_job()
        job.start()
        job.update_status(rate=77)

        self.assertEqual(job.get_current_state(), ('started', 77))


class TestNotification(BackgroundJobCommon):

    def test_progress_goes_to_the_owner_and_nobody_else(self):
        job = self.make_job()

        job.start()

        channels = [channel for channel, _message in self.notifications()]
        self.assertIn([self.env.cr.dbname, 'res.users', self.env.uid], channels,
                      "the owner's user record is the channel, not a guessable string")
        self.assertFalse([c for c in channels if c[1:2] == ['res.background_job']],
                         "no string channel anybody could subscribe to")

    def test_the_payload_says_how_the_job_is_going(self):
        job = self.make_job()
        job.start()

        job.update_status(rate=30, statusMsg="Working")

        _channel, message = self.notifications()[-1]
        self.assertEqual(message['type'], NOTIFICATION_TYPE)
        self.assertEqual(message['payload']['id'], job.id)
        self.assertEqual(message['payload']['completion_rate'], 30)
        self.assertEqual(message['payload']['current_status'], "Working")
        self.assertEqual(message['payload']['state'], 'started')

    def test_dates_travel_as_strings(self):
        job = self.make_job()

        job.start()

        _channel, message = self.notifications()[-1]
        self.assertIsInstance(message['payload']['started_on'], str)
        self.assertFalse(message['payload']['ended_on'])

    def test_nothing_is_published_when_nothing_changes(self):
        job = self.make_job()
        before = len(self.notifications())

        job.update_status(rate=10)  # not started, so no change

        self.assertEqual(len(self.notifications()), before)


class TestRunnable(BackgroundJobCommon):

    def test_a_well_formed_job_can_run(self):
        self.assertEqual(self.make_job()._check_runnable(), "")

    def test_an_unknown_model_is_reported(self):
        self.assertIn('not in the registry',
                      self.make_job(model='no.such.model')._check_runnable())

    def test_a_missing_target_record_is_reported(self):
        job = self.make_job()
        self.partner.unlink()

        self.assertIn('no target record', job._check_runnable())

    def test_a_missing_method_is_reported(self):
        self.assertIn('does not exist',
                      self.make_job(method='no_such_method')._check_runnable())

    def test_a_non_callable_attribute_is_reported(self):
        self.assertIn('not callable', self.make_job(method='name')._check_runnable())


class TestPrune(BackgroundJobCommon):

    def _aged(self, days, state):
        job = self.make_job()
        job.write({
            'state': state,
            'initialized_on': fields.Datetime.subtract(fields.Datetime.now(), days=days),
        })
        return job

    def test_old_finished_jobs_are_deleted(self):
        old = self._aged(DEFAULT_RETENTION_DAYS + 1, 'ended')

        self.env['res.background_job'].prune()

        self.assertFalse(old.exists())

    def test_recent_jobs_are_kept(self):
        recent = self._aged(DEFAULT_RETENTION_DAYS - 1, 'ended')

        self.env['res.background_job'].prune()

        self.assertTrue(recent.exists())

    def test_a_running_job_is_never_deleted(self):
        # However long it has been at it, a job that is still working is not stale.
        running = self._aged(DEFAULT_RETENTION_DAYS + 100, 'started')

        self.env['res.background_job'].prune()

        self.assertTrue(running.exists())

    def test_the_retention_period_is_configurable(self):
        self.env['ir.config_parameter'].sudo().set_int(RETENTION_DAYS_PARAM, 2)
        old = self._aged(3, 'ended')
        recent = self._aged(1, 'ended')

        self.env['res.background_job'].prune()

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_cleanup_can_be_switched_off(self):
        self.env['ir.config_parameter'].sudo().set_int(RETENTION_DAYS_PARAM, 0)
        old = self._aged(DEFAULT_RETENTION_DAYS + 100, 'ended')

        self.env['res.background_job'].prune()

        self.assertTrue(old.exists())


class TestAbortBeforeStart(BackgroundJobCommon):
    """A job that never ran still has to end up somewhere."""

    def test_a_job_that_never_started_can_be_aborted(self):
        job = self.make_job()

        job.abort(errorMsg="Cannot run this")

        self.assertEqual(job.state, 'aborted')
        self.assertEqual(job.error, "Cannot run this")

    def test_a_job_can_be_stopped_before_the_worker_takes_it(self):
        job = self.make_job()

        job.try_to_abort("Changed my mind")

        self.assertEqual(job.state, 'aborting')

    def test_a_job_asked_to_stop_does_not_start(self):
        job = self.make_job()
        job.try_to_abort()

        self.assertFalse(job.start(), "the worker must not run what was called off")
        self.assertEqual(job.state, 'aborting')
