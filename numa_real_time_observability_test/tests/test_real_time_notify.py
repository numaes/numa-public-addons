# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""What ``real_time_notify`` puts on the bus, and who can reach it."""

import json

from odoo.addons.base.tests.common import BaseCommon
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger

LOGGER = 'odoo.addons.numa_real_time_observability.models.real_time_observability_mixin'


class ObservabilityCommon(BaseCommon):
    _test_user_groups = ('base.group_user', 'base.group_system')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.observers = cls.env.ref('numa_real_time_observability.group_observer')
        cls.probe = cls.env['numa.observability.probe'].create({'name': "Probe"})

    def setUp(self):
        super().setUp()
        last = self.env['bus.bus'].sudo().search([], order='id desc', limit=1)
        self._bus_floor = last.id or 0

    def sent(self):
        """The bus rows written since this test started, oldest first.

        ``bus.bus`` creates its rows in a precommit hook, so the cursor has to
        be flushed before they exist.
        """
        self.env.cr.flush()
        return self.env['bus.bus'].sudo().search(
            [('id', '>', self._bus_floor)], order='id')

    def payloads(self):
        return [json.loads(row.message) for row in self.sent()]


class TestPayload(ObservabilityCommon):

    def test_a_notification_says_which_record_it_is_about(self):
        self.probe.real_time_notify({'event': 'state_changed'})

        payload = self.payloads()[0]
        self.assertEqual(payload['type'], 'observability/numa.observability.probe')
        self.assertEqual(payload['payload'], {
            'id': self.probe.id,
            'model': 'numa.observability.probe',
            'notification_data': {'event': 'state_changed'},
        })

    def test_the_notification_type_names_the_model(self):
        self.probe.real_time_notify()

        self.assertEqual(self.payloads()[0]['type'],
                         'observability/numa.observability.probe')

    def test_no_data_means_an_empty_mapping(self):
        self.probe.real_time_notify()

        self.assertEqual(self.payloads()[0]['payload']['notification_data'], {})

    @mute_logger(LOGGER)
    def test_data_that_is_not_a_dict_is_wrapped(self):
        self.probe.real_time_notify("a string")

        self.assertEqual(self.payloads()[0]['payload']['notification_data'],
                         {'data': "a string"})

    @mute_logger(LOGGER)
    def test_data_that_cannot_be_serialized_sends_nothing(self):
        sent = self.probe.real_time_notify({'record': self.probe})

        self.assertEqual(sent, 0)
        self.assertFalse(self.sent(), "a broken payload must not reach the bus")

    def test_the_caller_is_told_how_many_went_out(self):
        self.assertEqual(self.probe.real_time_notify(), 1)


class TestRecordset(ObservabilityCommon):

    def test_every_record_gets_its_own_notification(self):
        probes = self.env['numa.observability.probe'].create([
            {'name': "First"}, {'name': "Second"}, {'name': "Third"},
        ])

        sent = probes.real_time_notify({'event': 'created'})

        self.assertEqual(sent, 3)
        ids = [payload['payload']['id'] for payload in self.payloads()]
        self.assertEqual(ids, probes.ids,
                         "each notification must be about its own record")

    def test_an_empty_recordset_sends_nothing(self):
        sent = self.env['numa.observability.probe'].real_time_notify()

        self.assertEqual(sent, 0)
        self.assertFalse(self.sent())

    @mute_logger(LOGGER)
    def test_an_unsaved_record_is_skipped(self):
        draft = self.env['numa.observability.probe'].new({'name': "Unsaved"})

        self.assertEqual(draft.real_time_notify(), 0)
        self.assertFalse(self.sent())


class TestCondition(ObservabilityCommon):

    def test_only_the_records_that_match_are_published(self):
        probes = self.env['numa.observability.probe'].create([
            {'name': "Draft one", 'state': 'draft'},
            {'name': "Done one", 'state': 'done'},
        ])

        sent = probes.real_time_notify(condition=lambda probe: probe.state == 'done')

        self.assertEqual(sent, 1)
        self.assertEqual(self.payloads()[0]['payload']['id'], probes[1].id)

    @mute_logger(LOGGER)
    def test_a_condition_that_raises_skips_that_record_only(self):
        probes = self.env['numa.observability.probe'].create([
            {'name': "First"}, {'name': "Second"},
        ])

        def explode(probe):
            if probe == probes[0]:
                raise ValueError("no opinion")
            return True

        sent = probes.real_time_notify(condition=explode)

        self.assertEqual(sent, 1)
        self.assertEqual(self.payloads()[0]['payload']['id'], probes[1].id)


class TestChannel(ObservabilityCommon):

    def test_the_channel_is_the_observer_group(self):
        self.probe.real_time_notify()

        row = self.sent()
        self.assertEqual(len(row), 1)
        self.assertEqual(json.loads(row.channel),
                         [self.env.cr.dbname, 'res.groups', self.observers.id],
                         "the group record is the channel, not a guessable string")

    # ir.websocket._build_bus_channel_list subscribes a user to each of its
    # groups, so being in the group is being on the channel. It needs a live
    # request, hence the check on the group itself; the websocket path is
    # verified against a running server instead.

    def test_a_member_of_the_group_reaches_the_channel(self):
        member = new_test_user(
            self.env, login='numa_obs_member',
            groups='base.group_user,numa_real_time_observability.group_observer')

        self.assertIn(self.observers, member.all_group_ids)

    def test_a_plain_employee_does_not(self):
        outsider = new_test_user(self.env, login='numa_obs_outsider', groups='base.group_user')

        self.assertNotIn(self.observers, outsider.all_group_ids,
                         "the group is the channel: an outsider must not be on it")

    def test_an_administrator_reaches_the_channel(self):
        # base.group_system implies the observer group, so an administrator
        # sees what the mixin publishes without being granted anything else.
        administrator = new_test_user(
            self.env, login='numa_obs_admin', groups='base.group_user,base.group_system')

        self.assertIn(self.observers, administrator.all_group_ids)
