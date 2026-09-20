# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)

# External id of the group that is also the bus channel: a user in it receives
# the notifications, a user outside it cannot reach them.
OBSERVER_GROUP = 'numa_real_time_observability.group_observer'

# Notification types are what the client subscribes to, one per observed model
NOTIFICATION_TYPE = 'observability/%s'


class RealTimeObservabilityMixin(models.AbstractModel):
    """Let a model publish what happens to it, live, on the Odoo bus.

    Inherit the mixin and call :meth:`real_time_notify` where something worth
    watching happens::

        class MyModel(models.Model):
            _name = 'my.model'
            _inherit = ['my.model', 'real.time.observability.mixin']

            def action_done(self):
                self.write({'state': 'done'})
                self.real_time_notify({'event': 'state_changed', 'new_state': 'done'})

    The message goes to the ``Real-Time Observer`` group, under the
    notification type ``observability/<model_name>``, which is what a client
    subscribes to::

        busService.subscribe("observability/my.model", ({ id, model, notification_data }) => ...)

    The message is written in the current transaction, and the bus only signals
    it once that transaction commits. A rollback therefore notifies nobody.
    """
    _name = 'real.time.observability.mixin'
    _description = "Real-Time Observability Mixin"

    def _observability_payload(self, record, notification_data):
        """Build the message sent for one record.

        Override to add or rename what subscribers receive.
        """
        return {
            'id': record.id,
            'model': record._name,
            'notification_data': notification_data,
        }

    def real_time_notify(self, notification_data=False, condition=None):
        """Publish one notification per record on the observability bus.

        :param notification_data: a JSON-serializable dict sent along with each
            record. Anything else is wrapped under a ``data`` key.
        :param condition: optional callable taking a record and returning
            whether it is worth notifying
        :return: the number of notifications published
        """
        if not self:
            return 0

        if notification_data is False:
            notification_data = {}
        elif not isinstance(notification_data, dict):
            _logger.warning(
                "real_time_notify: notification_data should be a dict, got %s; "
                "sending it under a 'data' key",
                type(notification_data).__name__)
            notification_data = {'data': notification_data}

        try:
            json.dumps(notification_data)
        except (TypeError, ValueError) as error:
            _logger.error(
                "real_time_notify: %s on %s is not JSON serializable, nothing was sent: %s",
                type(notification_data).__name__, self._name, error)
            return 0

        observers = self.env.ref(OBSERVER_GROUP, raise_if_not_found=False)
        if not observers:
            _logger.warning("real_time_notify: the observer group is missing, nothing was sent")
            return 0

        bus = self.env['bus.bus']
        notification_type = NOTIFICATION_TYPE % self._name
        sent = 0
        for record in self:
            if not record.id:
                _logger.warning("real_time_notify: %s has no id yet, skipping it", record)
                continue
            if condition is not None:
                try:
                    if not condition(record):
                        continue
                except Exception as error:  # noqa: BLE001 - a bad condition must not break the caller
                    _logger.warning(
                        "real_time_notify: the condition raised on %s(%s), skipping it: %s",
                        self._name, record.id, error)
                    continue
            # The group record is the channel, so only its members receive
            # this; a string channel would be guessable by anyone.
            bus._sendone(observers, notification_type,
                         self._observability_payload(record, notification_data))
            sent += 1
        return sent
