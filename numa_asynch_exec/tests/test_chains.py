# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The fluent interface: what graph a chain of calls actually builds."""

from odoo.exceptions import ValidationError

from .common import AsynchCommon


class ChainCommon(AsynchCommon):

    def jobs_for(self, *method_names):
        """Return the jobs this test created for those method names, in order."""
        return self.own_jobs([('method_name', 'in', list(method_names))])

    def dependencies_of(self, job):
        return set(job.dependency_ids.depends_on_id.ids)


class TestAsynchExec(ChainCommon):

    def test_a_call_becomes_a_pending_job(self):
        with self.collect_queue():
            job_id = self.target.asynch_exec().write({'comment': "later"})

        job = self.env['numa.asynch.job'].browse(job_id)
        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.model_name, 'res.partner')
        self.assertEqual(job.method_name, 'write')
        self.assertEqual(job.res_ids, self.target.ids)
        self.assertEqual(job.args, [{'comment': "later"}])

    def test_the_method_is_not_called_yet(self):
        with self.collect_queue():
            self.target.asynch_exec().write({'comment': "later"})

        self.assertFalse(self.target.comment, "the call is deferred, not executed")

    def test_retry_settings_reach_the_job(self):
        with self.collect_queue():
            job_id = self.target.asynch_exec(retry=3, retry_delay=500).write({'comment': "x"})

        job = self.env['numa.asynch.job'].browse(job_id)
        self.assertEqual(job.max_retries, 3)
        self.assertEqual(job.retry_delay, 500)

    def test_the_job_is_queued(self):
        with self.collect_queue() as submitted:
            job_id = self.target.asynch_exec().write({'comment': "x"})

        self.assertEqual([entry['job_id'] for entry in submitted], [job_id])

    def test_the_caller_gets_an_id_not_a_sudo_recordset(self):
        with self.collect_queue():
            result = self.target.asynch_exec().write({'comment': "x"})

        self.assertIsInstance(result, int)

    def test_a_private_method_can_be_deferred(self):
        with self.collect_queue():
            job_id = self.target.asynch_exec()._compute_display_name()

        self.assertEqual(self.env['numa.asynch.job'].browse(job_id).method_name,
                         '_compute_display_name')


class TestSequentialChain(ChainCommon):

    def test_the_second_call_waits_for_the_first(self):
        with self.collect_queue() as submitted:
            self.target.job_wait().write({'comment': "first"}).copy()

        first, second = self.jobs_for('write', 'copy')
        self.assertEqual(first.state, 'pending')
        self.assertEqual(second.state, 'waiting')
        self.assertEqual(self.dependencies_of(second), {first.id})
        self.assertEqual([entry['job_id'] for entry in submitted], [first.id],
                         "only the job that can run is queued")

    def test_a_three_step_chain_is_a_line(self):
        with self.collect_queue():
            self.target.job_wait().write({'comment': "a"}).copy().read()

        write, copy, read = self.jobs_for('write', 'copy', 'read')
        self.assertEqual(self.dependencies_of(write), set())
        self.assertEqual(self.dependencies_of(copy), {write.id})
        self.assertEqual(self.dependencies_of(read), {copy.id})


class TestParallelChain(ChainCommon):

    def test_job_wait_in_the_middle_opens_a_parallel_branch(self):
        # write and copy run together, read waits for both
        with self.collect_queue() as submitted:
            self.target.job_wait().write({'comment': "a"}).job_wait().copy().read()

        write, copy, read = self.jobs_for('write', 'copy', 'read')
        self.assertEqual(self.dependencies_of(write), set())
        self.assertEqual(self.dependencies_of(copy), set(), "the branch starts where write did")
        self.assertEqual(self.dependencies_of(read), {write.id, copy.id})
        self.assertEqual(sorted(entry['job_id'] for entry in submitted),
                         sorted([write.id, copy.id]))

    def test_the_chain_continues_after_the_join(self):
        with self.collect_queue():
            (self.target.job_wait()
             .write({'comment': "a"})
             .job_wait().copy()
             .read()
             .exists())

        write, copy, read, exists = self.jobs_for('write', 'copy', 'read', 'exists')
        self.assertEqual(self.dependencies_of(read), {write.id, copy.id})
        self.assertEqual(self.dependencies_of(exists), {read.id})

    def test_two_branches_join_together(self):
        with self.collect_queue():
            (self.target.job_wait()
             .write({'comment': "a"})
             .job_wait().copy()
             .job_wait().exists()
             .read())

        write, copy, exists, read = self.jobs_for('write', 'copy', 'exists', 'read')
        self.assertEqual(self.dependencies_of(copy), set())
        self.assertEqual(self.dependencies_of(exists), set())
        self.assertEqual(self.dependencies_of(read), {write.id, copy.id, exists.id})


class TestRelease(ChainCommon):

    def test_a_waiting_job_is_released_when_its_dependency_finishes(self):
        with self.collect_queue():
            self.target.job_wait().write({'comment': "a"}).copy()
        first, second = self.jobs_for('write', 'copy')

        first.write({'state': 'done'})
        with self.collect_queue() as submitted:
            first._trigger_dependents()

        self.assertEqual(second.state, 'pending')
        self.assertEqual([entry['job_id'] for entry in submitted], [second.id])

    def test_a_job_waits_until_every_dependency_is_done(self):
        with self.collect_queue():
            self.target.job_wait().write({'comment': "a"}).job_wait().copy().read()
        write, copy, read = self.jobs_for('write', 'copy', 'read')

        write.write({'state': 'done'})
        with self.collect_queue() as submitted:
            write._trigger_dependents()

        self.assertEqual(read.state, 'waiting', "copy has not finished yet")
        self.assertFalse(submitted)

        copy.write({'state': 'done'})
        with self.collect_queue() as submitted:
            copy._trigger_dependents()

        self.assertEqual(read.state, 'pending')
        self.assertEqual([entry['job_id'] for entry in submitted], [read.id])

    def test_a_job_is_released_once(self):
        with self.collect_queue():
            self.target.job_wait().write({'comment': "a"}).copy()
        first, second = self.jobs_for('write', 'copy')
        first.write({'state': 'done'})

        with self.collect_queue() as submitted:
            self.assertTrue(second._release())
            self.assertFalse(second._release(), "two dependencies finishing must not queue it twice")

        self.assertEqual(len(submitted), 1)


class TestDependencyIntegrity(ChainCommon):

    def test_a_job_cannot_depend_on_itself(self):
        job = self.make_job()

        with self.assertRaises(ValidationError):
            self.env['numa.asynch.job.dependency'].create({
                'job_id': job.id, 'depends_on_id': job.id,
            })

    def test_a_direct_cycle_is_refused(self):
        first, second = self.make_job(), self.make_job()
        self.env['numa.asynch.job.dependency'].create({
            'job_id': second.id, 'depends_on_id': first.id,
        })

        with self.assertRaises(ValidationError):
            self.env['numa.asynch.job.dependency'].create({
                'job_id': first.id, 'depends_on_id': second.id,
            })

    def test_a_long_cycle_is_refused(self):
        first, second, third = self.make_job(), self.make_job(), self.make_job()
        Dependency = self.env['numa.asynch.job.dependency']
        Dependency.create({'job_id': second.id, 'depends_on_id': first.id})
        Dependency.create({'job_id': third.id, 'depends_on_id': second.id})

        with self.assertRaises(ValidationError):
            Dependency.create({'job_id': first.id, 'depends_on_id': third.id})

    def test_a_diamond_is_not_a_cycle(self):
        top, left, right, bottom = (self.make_job() for _ in range(4))
        Dependency = self.env['numa.asynch.job.dependency']
        Dependency.create({'job_id': left.id, 'depends_on_id': top.id})
        Dependency.create({'job_id': right.id, 'depends_on_id': top.id})
        Dependency.create({'job_id': bottom.id, 'depends_on_id': left.id})
        Dependency.create({'job_id': bottom.id, 'depends_on_id': right.id})

        self.assertEqual(self.dependencies_of(bottom), {left.id, right.id})
