# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2024
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
import json

import odoo
from odoo import models, api

_logger = logging.getLogger(__name__)


class RealTimeObservabilityMixin(models.AbstractModel):
    """
    Mixin that provides real-time observability capabilities to any Odoo model.
    
    This mixin adds a method `real_time_notify()` that sends notifications to
    the Odoo bus system. Notifications are only sent after a successful commit,
    ensuring data consistency.
    
    Usage:
        class MyModel(models.Model):
            _name = 'my.model'
            _inherit = ['my.model', 'real.time.observability.mixin']
            
            def my_method(self):
                # Your business logic
                self.write({'state': 'done'})
                # Send notification after successful commit
                self.real_time_notify({'event': 'state_changed', 'new_state': 'done'})
    
    The notification will be sent to the bus with the topic:
    `observability/<model_name>`
    
    The message will contain:
    - id: The record ID
    - notification_data: The data passed to real_time_notify()
    """
    _name = 'real.time.observability.mixin'
    _description = 'Real-Time Observability Mixin'

    def _validate_serializable(self, data):
        """
        Validate that data can be serialized to JSON.
        
        :param data: Data to validate
        :type data: any
        :return: True if serializable, False otherwise
        :rtype: bool
        """
        try:
            json.dumps(data)
            return True
        except (TypeError, ValueError) as e:
            _logger.warning(
                "real_time_notify: Data is not JSON serializable: %s",
                str(e)
            )
            return False

    def real_time_notify(self, notification_data=False, condition=None):
        """
        Send a real-time notification through the Odoo bus system.
        
        The notification will only be sent after a successful commit, ensuring
        that the data is persisted before notifying listeners.
        
        :param notification_data: Optional dictionary with additional data to include
                                  in the notification. Defaults to False (empty dict).
                                  Must be JSON serializable.
        :type notification_data: dict or False
        
        :param condition: Optional callable that receives the record and returns True
                         if the notification should be sent. If None, notification is
                         always sent (if record has ID).
        :type condition: callable or None
        
        :return: None
        """
        if not self:
            return
        
        # Ensure notification_data is a dict
        if notification_data is False:
            notification_data = {}
        elif not isinstance(notification_data, dict):
            _logger.warning(
                "real_time_notify: notification_data should be a dict, got %s. "
                "Converting to dict with 'data' key.",
                type(notification_data).__name__
            )
            notification_data = {'data': notification_data}
        
        # Validate that notification_data is JSON serializable
        if not self._validate_serializable(notification_data):
            _logger.error(
                "real_time_notify: notification_data is not JSON serializable. "
                "Notification will not be sent."
            )
            return
        
        # Get model name for the topic
        model_name = self._name
        
        # Store environment data for post-commit hook (avoid closure issues)
        dbname = self.env.cr.dbname
        uid = self.env.uid
        context = self.env.context.copy()
        
        # Prepare notification data for each record
        for record in self:
            if not record.id:
                _logger.warning(
                    "real_time_notify: Record %s has no ID yet. "
                    "Notification will be skipped.",
                    record
                )
                continue
            
            # Check condition if provided
            if condition is not None:
                try:
                    if not condition(record):
                        _logger.debug(
                            "real_time_notify: Condition not met for record %s (ID: %s). "
                            "Skipping notification.",
                            model_name, record.id
                        )
                        continue
                except Exception as e:
                    _logger.warning(
                        "real_time_notify: Error evaluating condition for %s (ID: %s): %s. "
                        "Skipping notification.",
                        model_name, record.id, str(e)
                    )
                    continue
            
            # Prepare the message
            message = {
                'id': record.id,
                'notification_data': notification_data,
            }
            
            # Store data for post-commit hook (capture in closure)
            record_id = record.id
            
            # Schedule notification to be sent after successful commit
            @self.env.cr.postcommit.add
            def _send_notification():
                try:
                    # Get registry using the captured dbname
                    registry = odoo.modules.registry.Registry(dbname)
                    if not registry:
                        _logger.error(
                            "real_time_notify: Could not get registry for database %s",
                            dbname
                        )
                        return
                    
                    # Get a new cursor and environment for the post-commit operation
                    with registry.cursor() as cr:
                        env = api.Environment(cr, uid, context)
                        bus_model = env['bus.bus']
                        
                        # Verify the record still exists
                        model_obj = env[model_name]
                        if not model_obj.browse(record_id).exists():
                            _logger.debug(
                                "real_time_notify: Record %s (ID: %s) no longer exists. "
                                "Skipping notification.",
                                model_name, record_id
                            )
                            return
                        
                        # Send notification to bus
                        channel = f'observability/{model_name}'
                        bus_model._sendone(channel, 'notification', message)
                        cr.commit()
                        
                        _logger.debug(
                            "real_time_notify: Sent notification for %s (ID: %s) "
                            "to channel %s",
                            model_name, record_id, channel
                        )
                except Exception as e:
                    # Log error but don't break the main transaction
                    _logger.error(
                        "real_time_notify: Error sending notification for %s (ID: %s): %s",
                        model_name, record_id, str(e),
                        exc_info=True
                    )
