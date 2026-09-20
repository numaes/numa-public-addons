# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""Who may touch the job table.

A row here names a model and a method the server will call, and it carries the
traceback of whatever went wrong. Neither is everybody's business.
"""

from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user

from .common import BackgroundJobCommon


class TestJobAccess(BackgroundJobCommon):

    def setUp(self):
        super().setUp()
        self.employee = new_test_user(self.env, login='numa_bj_employee',
                                      groups='base.group_user')
        self.other = new_test_user(self.env, login='numa_bj_other',
                                   groups='base.group_user')

    def test_an_employee_cannot_create_a_job(self):
        Job = self.env['res.background_job'].with_user(self.employee)

        with self.assertRaises(AccessError):
            Job.create({
                'name': "Not yours to make",
                'model': 'res.users',
                'res_id': self.env.ref('base.user_admin').id,
                'method': '_compute_display_name',
                'user_id': self.employee.id,
            })

    def test_an_employee_reads_their_own_job(self):
        job = self.make_job(user_id=self.employee.id)

        self.assertEqual(job.with_user(self.employee).name, "Test job")

    def test_an_employee_cannot_read_somebody_elses_job(self):
        job = self.make_job(user_id=self.employee.id)

        with self.assertRaises(AccessError):
            job.with_user(self.other).read(['error'])

    def test_an_employee_can_ask_their_own_job_to_stop(self):
        job = self.make_job(user_id=self.employee.id)
        job.start()

        job.with_user(self.employee).try_to_abort("Enough")

        self.assertEqual(job.state, 'aborting')

    def test_an_employee_cannot_stop_somebody_elses_job(self):
        job = self.make_job(user_id=self.employee.id)
        job.start()

        with self.assertRaises(AccessError):
            job.with_user(self.other).try_to_abort()

    def test_an_employee_cannot_delete_a_job(self):
        job = self.make_job(user_id=self.employee.id)

        with self.assertRaises(AccessError):
            job.with_user(self.employee).unlink()

    def test_launch_works_for_an_employee(self):
        # The point of closing the table: a user still starts jobs, through
        # server code that goes past the ACL on purpose.
        job = self.env['res.background_job'].with_user(self.employee)._launch(
            "Launched by an employee", self.partner, 'write')

        self.assertEqual(job.user_id, self.employee)

    def test_an_employee_cannot_end_somebody_elses_job(self):
        job = self.make_job(user_id=self.employee.id)
        job.start()

        with self.assertRaises(AccessError):
            job.with_user(self.other).end("Not yours to finish")

    def test_an_employee_cannot_read_somebody_elses_progress(self):
        job = self.make_job(user_id=self.employee.id)
        job.start()

        with self.assertRaises(AccessError):
            job.with_user(self.other).get_current_state()
