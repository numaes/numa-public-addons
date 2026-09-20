# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The job lifecycle: what can run, who claims it, what a failure does."""

from psycopg2.errors import SerializationFailure

from odoo.exceptions import UserError
from odoo.tools import mute_logger

from .common import AsynchCommon
from ..models.numa_asynch_job import MAX_CONCURRENCY_RETRIES


class TestRunnable(AsynchCommon):

    def test_a_well_formed_job_can_run(self):
        self.assertEqual(self.make_job()._check_runnable(), "")

    def test_an_unknown_model_is_reported(self):
        problem = self.make_job(model_name='no.such.model')._check_runnable()

        self.assertIn('not in the registry', problem)

    def test_a_missing_method_is_reported(self):
        problem = self.make_job(method_name='no_such_method')._check_runnable()

        self.assertIn('does not exist', problem)

    def test_a_non_callable_attribute_is_reported(self):
        problem = self.make_job(method_name='name')._check_runnable()

        self.assertIn('not callable', problem)

    def test_deleted_target_records_are_reported(self):
        job = self.make_job()
        self.target.unlink()

        self.assertIn('no target record left', job._check_runnable())

    def test_a_job_without_target_records_is_runnable(self):
        # A model-level method (@api.model) has no records to act on.
        job = self.make_job(res_ids=[], method_name='search')

        self.assertEqual(job._check_runnable(), "")


class TestClaim(AsynchCommon):

    def test_claiming_moves_the_job_to_running(self):
        job = self.make_job()

        self.assertTrue(job._claim())
        self.assertEqual(job.state, 'running')

    def test_a_job_is_claimed_once(self):
        job = self.make_job()
        job._claim()

        self.assertFalse(job._claim(), "the executor and the cron must not both run it")

    def test_a_waiting_job_can_be_claimed(self):
        job = self.make_job(state='waiting')

        self.assertTrue(job._claim())

    def test_a_finished_job_is_not_claimed_again(self):
        for state in ('done', 'failed', 'running'):
            job = self.make_job(state=state)

            self.assertFalse(job._claim(), "state %s" % state)


class TestExecute(AsynchCommon):

    def test_the_method_is_called_on_the_target(self):
        self.make_job()._execute()

        # comment is an Html field, so the text comes back wrapped
        self.assertIn("written by the job", self.target.comment)

    def test_keyword_arguments_are_passed_through(self):
        job = self.make_job(method_name='copy', args=[], kwargs={'default': {'name': "Copy"}})

        job._execute()

        self.assertTrue(self.env['res.partner'].search([('name', '=', "Copy")]))

    def test_the_stored_context_reaches_the_method(self):
        job = self.make_job(method_name='read', args=[['display_name']], kwargs={},
                            context={'lang': 'en_US'})

        self.assertTrue(job._execute())


class TestFailure(AsynchCommon):

    @mute_logger('odoo.addons.numa_asynch_exec.models.numa_asynch_job')
    def test_without_retries_a_failure_is_final(self):
        job = self.make_job(max_retries=0)

        job._record_failure(ValueError("boom"))

        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.retry_count, 0)
        self.assertEqual(job.error, "ValueError: boom")

    @mute_logger('odoo.addons.numa_asynch_exec.models.numa_asynch_job')
    def test_a_retry_puts_the_job_back_in_the_queue(self):
        job = self.make_job(max_retries=2)

        job._record_failure(ValueError("boom"))

        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.retry_count, 1)

    @mute_logger('odoo.addons.numa_asynch_exec.models.numa_asynch_job')
    def test_retries_run_out(self):
        job = self.make_job(max_retries=2)
        for _attempt in range(3):
            job._record_failure(ValueError("boom"))

        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.retry_count, 2)

    @mute_logger('odoo.addons.numa_asynch_exec.models.numa_asynch_job')
    def test_an_unbounded_retry_reuses_the_same_record(self):
        job = self.make_job(max_retries=-1)
        before = len(self.own_jobs())

        for _attempt in range(5):
            job._record_failure(ValueError("boom"))

        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.retry_count, 5)
        self.assertEqual(len(self.own_jobs()), before,
                         "a polling job must not grow the table once per attempt")


class TestQueue(AsynchCommon):

    def test_a_job_is_submitted_with_what_the_worker_needs(self):
        job = self.make_job(retry_delay=250, context={'lang': 'en_US'})

        with self.collect_queue() as submitted:
            job._queue()

        self.assertEqual(submitted, [{
            'job_id': job.id,
            'db_name': self.env.cr.dbname,
            'context': {'lang': 'en_US'},
            'delay': 250,
        }])


class TestRecovery(AsynchCommon):

    def setUp(self):
        super().setUp()
        # A worker may have committed jobs into this database; recovery would
        # pick them up too, and this test is about the ones it creates.
        self.env['numa.asynch.job'].search(
            [('state', 'in', ('pending', 'waiting'))]).write({'state': 'failed'})

    def test_pending_jobs_are_queued_again(self):
        job = self.make_job(state='pending')

        with self.collect_queue() as submitted:
            self.env['numa.asynch.job']._recover_pending_jobs()

        self.assertIn(job.id, [entry['job_id'] for entry in submitted])

    def test_finished_jobs_are_left_alone(self):
        done = self.make_job(state='done')
        failed = self.make_job(state='failed')

        with self.collect_queue() as submitted:
            self.env['numa.asynch.job']._recover_pending_jobs()

        queued = [entry['job_id'] for entry in submitted]
        self.assertNotIn(done.id, queued)
        self.assertNotIn(failed.id, queued)

    def test_a_job_still_waiting_is_not_queued(self):
        first = self.make_job(state='pending')
        second = self.make_job(state='waiting')
        self.env['numa.asynch.job.dependency'].create({
            'job_id': second.id, 'depends_on_id': first.id,
        })

        with self.collect_queue() as submitted:
            self.env['numa.asynch.job']._recover_pending_jobs()

        queued = [entry['job_id'] for entry in submitted]
        self.assertIn(first.id, queued)
        self.assertNotIn(second.id, queued)


class TestConcurrencyRetry(AsynchCommon):
    """A database conflict is a collision, not a defect: it gets its own budget."""

    def _conflict(self):
        return SerializationFailure("could not serialize access due to concurrent update")

    def test_a_conflict_is_retried_even_without_retries_configured(self):
        job = self.make_job(max_retries=0)

        job._record_failure(self._conflict())

        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.concurrency_retries, 1)
        self.assertEqual(job.retry_count, 0, "the caller's attempts are not spent on a collision")

    @mute_logger('odoo.addons.numa_asynch_exec.models.numa_asynch_job')
    def test_a_job_that_keeps_colliding_eventually_fails(self):
        job = self.make_job(max_retries=0)

        for _attempt in range(MAX_CONCURRENCY_RETRIES + 1):
            job._record_failure(self._conflict())

        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.concurrency_retries, MAX_CONCURRENCY_RETRIES)

    @mute_logger('odoo.addons.numa_asynch_exec.models.numa_asynch_job')
    def test_a_real_failure_clears_the_conflict_budget(self):
        job = self.make_job(max_retries=2)
        job._record_failure(self._conflict())

        job._record_failure(ValueError("boom"))

        self.assertEqual(job.retry_count, 1)
        self.assertEqual(job.concurrency_retries, 0)

    def test_a_colliding_job_backs_off(self):
        job = self.make_job(retry_delay=100)
        self.assertEqual(job._next_delay(), 100)

        job.write({'concurrency_retries': 3})
        self.assertGreater(job._next_delay(), 100)

    def test_the_backoff_is_bounded(self):
        job = self.make_job(retry_delay=0)
        job.write({'concurrency_retries': 50})

        self.assertEqual(job._next_delay(), 3200)


class TestRequeue(AsynchCommon):
    """The way out for a job that got stuck."""

    def test_a_failed_job_goes_back_to_the_queue(self):
        job = self.make_job(state='failed', retry_count=3, error="ValueError: boom")

        with self.collect_queue() as submitted:
            job.action_requeue()

        self.assertEqual(job.state, 'pending')
        self.assertEqual([entry['job_id'] for entry in submitted], [job.id])

    def test_requeueing_gives_a_fresh_budget(self):
        job = self.make_job(state='failed', retry_count=3, concurrency_retries=5,
                            error="ValueError: boom")

        with self.collect_queue():
            job.action_requeue()

        self.assertEqual(job.retry_count, 0)
        self.assertEqual(job.concurrency_retries, 0)
        self.assertFalse(job.error)

    def test_a_job_stuck_in_running_can_be_requeued(self):
        # A process that died leaves its job in 'running' forever.
        job = self.make_job(state='running')

        with self.collect_queue() as submitted:
            job.action_requeue()

        self.assertEqual(job.state, 'pending')
        self.assertEqual(len(submitted), 1)

    def test_a_job_with_unmet_dependencies_goes_back_to_waiting(self):
        blocker = self.make_job(state='pending')
        blocked = self.make_job(state='failed')
        self.env['numa.asynch.job.dependency'].create({
            'job_id': blocked.id, 'depends_on_id': blocker.id,
        })

        with self.collect_queue() as submitted:
            blocked.action_requeue()

        self.assertEqual(blocked.state, 'waiting')
        self.assertFalse(submitted, "it must not run before what it waits for")

    def test_a_finished_job_is_not_run_again(self):
        job = self.make_job(state='done')

        with self.assertRaises(UserError) as caught:
            job.action_requeue()

        self.assertIn('1', str(caught.exception), "the message names how many")
        self.assertEqual(job.state, 'done')

    def test_requeueing_several_jobs_at_once(self):
        first = self.make_job(state='failed')
        second = self.make_job(state='running')

        with self.collect_queue() as submitted:
            (first | second).action_requeue()

        self.assertEqual(first.state, 'pending')
        self.assertEqual(second.state, 'pending')
        self.assertEqual(len(submitted), 2)


class TestDisplayName(AsynchCommon):

    def test_a_job_says_what_it_calls(self):
        job = self.make_job()

        self.assertEqual(job.display_name, 'res.partner.write #%s' % job.id)
