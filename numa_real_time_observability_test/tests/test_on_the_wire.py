# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The notification on a real websocket: it reaches an observer, and only one."""

import json

import websocket

from odoo.addons.bus.tests.common import WebsocketCase
from odoo.tests.common import new_test_user

OBSERVER_GROUP = 'numa_real_time_observability.group_observer'
PROBE_TYPE = 'observability/numa.observability.probe'


class TestOnTheWire(WebsocketCase):

    def _connect_as(self, login, groups):
        """Open a websocket for a freshly created user."""
        new_test_user(self.env, login=login, password=login, groups=groups)
        session = self.authenticate(login, login)
        return self.websocket_connect(cookie='session_id=%s' % session.sid)

    def _notifications_of_interest(self, client):
        """Read one batch and keep what this module published."""
        try:
            batch = json.loads(client.recv())
        except websocket.WebSocketTimeoutException:
            return []
        return [n for n in batch if n['message']['type'] == PROBE_TYPE]

    def test_an_observer_receives_the_notification(self):
        probe = self.env['numa.observability.probe'].create({'name': "On the wire"})
        client = self._connect_as('numa_obs_wire', 'base.group_user,%s' % OBSERVER_GROUP)
        self.subscribe(client, [], last=self.env['bus.bus']._bus_last_id())

        probe.real_time_notify({'event': 'ping'})
        self.trigger_notification_dispatching()

        received = self._notifications_of_interest(client)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['message']['payload'], {
            'id': probe.id,
            'model': 'numa.observability.probe',
            'notification_data': {'event': 'ping'},
        })

    def test_an_employee_outside_the_group_receives_nothing(self):
        probe = self.env['numa.observability.probe'].create({'name': "Not for you"})
        client = self._connect_as('numa_obs_wire_out', 'base.group_user')
        self.subscribe(client, [], last=self.env['bus.bus']._bus_last_id())

        probe.real_time_notify({'event': 'ping'})
        self.trigger_notification_dispatching()

        client.settimeout(2)
        self.assertEqual(self._notifications_of_interest(client), [],
                         "the group is the channel: an outsider must hear nothing")

    def test_guessing_the_old_channel_name_gets_nothing(self):
        # The channel used to be this guessable string; anyone could listen in.
        probe = self.env['numa.observability.probe'].create({'name': "Guess me"})
        client = self._connect_as('numa_obs_wire_guess', 'base.group_user')
        self.subscribe(client, ['observability/numa.observability.probe'],
                       last=self.env['bus.bus']._bus_last_id())

        probe.real_time_notify({'event': 'ping'})
        self.trigger_notification_dispatching()

        client.settimeout(2)
        self.assertEqual(self._notifications_of_interest(client), [],
                         "subscribing to the old string channel must not work any more")
