# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""Who may touch the job table.

A row in this table names a model and a method that a worker thread runs as
superuser. Anyone able to write one can therefore run anything.
"""

from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user

from .common import AsynchCommon


class TestJobAccess(AsynchCommon):

    def setUp(self):
        super().setUp()
        self.employee = new_test_user(
            self.env, login='numa_asynch_employee', groups='base.group_user')

    def test_an_employee_cannot_create_a_job(self):
        Job = self.env['numa.asynch.job'].with_user(self.employee)

        with self.assertRaises(AccessError):
            Job.create({
                'db_name': self.env.cr.dbname,
                'model_name': 'res.users',
                'res_ids': [self.env.ref('base.user_admin').id],
                'method_name': 'write',
                'args': [{'login': 'stolen'}],
            })

    def test_an_employee_cannot_read_the_jobs(self):
        job = self.make_job()

        with self.assertRaises(AccessError):
            job.with_user(self.employee).read(['method_name'])

    def test_an_employee_cannot_create_a_dependency(self):
        first, second = self.make_job(), self.make_job()
        Dependency = self.env['numa.asynch.job.dependency'].with_user(self.employee)

        with self.assertRaises(AccessError):
            Dependency.create({'job_id': second.id, 'depends_on_id': first.id})

    def test_an_employee_can_still_defer_a_call(self):
        # asynch_exec goes through sudo(), which is what makes the closed ACL
        # safe rather than crippling.
        target = self.target.with_user(self.employee)

        with self.collect_queue():
            job_id = target.asynch_exec().read(['display_name'])

        self.assertTrue(self.env['numa.asynch.job'].browse(job_id).exists())
