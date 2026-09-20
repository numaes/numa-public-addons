# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

import json
from contextlib import contextmanager
from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon

from .. import worker


class BackgroundJobCommon(BaseCommon):
    """Base for the job tests.

    ``_write_status`` opens a cursor of its own and commits it, which is the
    whole point of the design. ``registry_test_mode`` makes that cursor a
    savepoint on the test's own, so the commits land inside the test
    transaction and are rolled back with it.
    """
    _test_user_groups = ('base.group_user', 'base.group_system')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enterClassContext(cls.registry_test_mode())
        cls.partner = cls.env['res.partner'].create({'name': "Job target"})

    def setUp(self):
        super().setUp()
        last = self.env['bus.bus'].sudo().search([], order='id desc', limit=1)
        self._bus_floor = last.id or 0

    @contextmanager
    def collect_threads(self):
        """Capture the workers a commit would start, instead of starting them."""
        started = []
        with patch.object(worker, 'start_worker',
                          lambda *args, **kwargs: started.append(args)):
            yield started

    def run_postcommit(self):
        """Fire what ``_spawn`` deferred, without committing the test cursor."""
        callbacks = list(self.env.cr.postcommit._funcs)
        self.env.cr.postcommit._funcs.clear()
        for callback in callbacks:
            callback()

    def make_job(self, **values):
        defaults = {
            'name': "Test job",
            'model': 'res.partner',
            'res_id': self.partner.id,
            'method': 'write',
            'user_id': self.env.uid,
        }
        defaults.update(values)
        with self.collect_threads():
            job = self.env['res.background_job'].create(defaults)
            self.run_postcommit()
        return job

    def notifications(self):
        """The bus messages written since this test started, oldest first."""
        self.env.cr.flush()
        rows = self.env['bus.bus'].sudo().search(
            [('id', '>', self._bus_floor)], order='id')
        return [(json.loads(row.channel), json.loads(row.message)) for row in rows]
