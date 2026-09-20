# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from contextlib import contextmanager
from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon

from .. import utils


class AsynchCommon(BaseCommon):
    """Base for the job tests: a target record and a queue that does not defer.

    A real job reaches the executor through a postcommit callback, which a
    test cursor never fires. ``collect_queue`` runs those callbacks at once
    and records what would have been submitted, so the queueing contract is
    asserted without starting a thread.
    """
    _test_user_groups = ('base.group_user', 'base.group_system')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.target = cls.env['res.partner'].create({'name': "Asynch target"})

    def setUp(self):
        super().setUp()
        # Jobs committed by a real worker outlive any test transaction, so a
        # test only ever looks at the rows it created itself.
        last = self.env['numa.asynch.job'].search([], order='id desc', limit=1)
        self._job_floor = last.id or 0

    def own_jobs(self, domain=None):
        """The jobs this test created, in creation order."""
        return self.env['numa.asynch.job'].search(
            [('id', '>', self._job_floor)] + (domain or []), order='id')

    @contextmanager
    def collect_queue(self):
        submitted = []

        def fake_submit(job_id, db_name, context, delay=0):
            submitted.append({
                'job_id': job_id, 'db_name': db_name, 'context': context, 'delay': delay,
            })

        def run_now(_callbacks, func):
            func()

        with patch.object(utils, 'submit_job', fake_submit), \
             patch.object(type(self.env.cr.postcommit), 'add', run_now):
            yield submitted

    def make_job(self, **values):
        """Create a job that would write a comment on the target partner."""
        defaults = {
            'db_name': self.env.cr.dbname,
            'model_name': 'res.partner',
            'res_ids': self.target.ids,
            'method_name': 'write',
            'args': [{'comment': "written by the job"}],
            'kwargs': {},
            'context': {},
            'uid': self.env.uid,
        }
        defaults.update(values)
        return self.env['numa.asynch.job'].create(defaults)
