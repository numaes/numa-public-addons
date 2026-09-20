# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The helpers that turn a call into something a Json field accepts."""

from datetime import date, datetime

from .common import AsynchCommon
from .. import utils


class TestSerialization(AsynchCommon):

    def test_a_recordset_becomes_its_ids(self):
        self.assertEqual(utils.make_json_serializable(self.target), self.target.ids)

    def test_dates_become_iso_strings(self):
        self.assertEqual(utils.make_json_serializable(date(2026, 9, 20)), '2026-09-20')
        self.assertEqual(utils.make_json_serializable(datetime(2026, 9, 20, 17, 5)),
                         '2026-09-20T17:05:00')

    def test_containers_are_converted_in_depth(self):
        converted = utils.make_json_serializable(
            {'records': (self.target, [date(2026, 1, 1)])})

        self.assertEqual(converted, {'records': [self.target.ids, ['2026-01-01']]})

    def test_tuples_become_lists(self):
        self.assertEqual(utils.make_json_serializable((1, 2)), [1, 2])

    def test_scalars_are_left_alone(self):
        for value in (1, 1.5, True, None, 'text'):
            self.assertEqual(utils.make_json_serializable(value), value)

    def test_dict_keys_become_strings(self):
        self.assertEqual(utils.make_json_serializable({1: 'one'}), {'1': 'one'})


class TestExecutor(AsynchCommon):

    def test_the_pool_is_built_once(self):
        first = utils.get_asynch_executor()
        second = utils.get_asynch_executor()

        self.assertIs(first, second)

    def test_a_worker_failure_is_swallowed(self):
        # run_job is the top of a worker thread: nothing above it would catch.
        with self.assertLogs('odoo.addons.numa_asynch_exec.utils', level='ERROR'):
            utils.run_job(-1, 'no such database', {})
