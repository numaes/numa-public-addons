# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging
import json

_logger = logging.getLogger(__name__)

class FsmInstance(models.Model):
    """
    Extension of fsm.instance to add Actor Model capabilities.
    
    Each FSM instance can now:
    - Publish events to topics (publish)
    - Receive notifications from topics (notify)
    - Handle topic-specific messages via dynamic dispatcher
    """
    _inherit = 'fsm.instance'

    # Computed field to show subscription count
    subscription_count = fields.Integer(
        string='Active Subscriptions',
        compute='_compute_subscription_count',
        help="Number of active topic subscriptions for this FSM instance"
    )

    def _compute_subscription_count(self):
        """Compute the number of active subscriptions for this FSM instance."""
        for instance in self:
            instance.subscription_count = self.env['numa.fsm.subscription'].search_count([
                ('subscriber_fsm_id', '=', instance.id),
                ('is_active', '=', True)
            ])

    def publish(self, topic_name, payload=None):
        """
        Publish an event to a topic.
        
        This method implements the "Publisher" side of the Pub/Sub pattern.
        It finds all active subscribers to the topic and asynchronously delivers
        the message to each one.
        
        :param topic_name: Name of the topic to publish to (will be normalized)
        :param payload: Dictionary or JSON-serializable data to send (optional)
        :return: Number of subscribers notified
        
        Example:
            self.publish('sale_order_confirmed', {'order_id': 123, 'amount': 1000.0})
        """
        self.ensure_one()
        
        if payload is None:
            payload = {}
        
        # Normalize topic name
        topic_model = self.env['numa.fsm.topic']
        normalized_name = topic_model.normalize_topic_name(topic_name)
        
        # Find the topic
        topic = topic_model.search([('name', '=', normalized_name)], limit=1)
        if not topic:
            _logger.warning(
                f"Topic '{normalized_name}' not found. Publishing anyway (Schema-on-Read philosophy). "
                f"FSM Instance: {self.id}"
            )
            # In Schema-on-Read, we don't fail if topic doesn't exist
            # We just log and continue (the topic might be created later)
            return 0
        
        if not topic.active:
            _logger.warning(
                f"Topic '{normalized_name}' is inactive. Skipping publication. "
                f"FSM Instance: {self.id}"
            )
            return 0
        
        # Find all active subscriptions for this topic
        subscriptions = self.env['numa.fsm.subscription'].search([
            ('topic_id', '=', topic.id),
            ('is_active', '=', True)
        ])
        
        if not subscriptions:
            _logger.debug(
                f"No active subscriptions found for topic '{normalized_name}'. "
                f"FSM Instance: {self.id}"
            )
            return 0
        
        # Serialize payload to JSON string for async delivery
        try:
            if isinstance(payload, str):
                # If it's already a string, try to parse it to validate JSON
                json.loads(payload)
                payload_str = payload
            else:
                payload_str = json.dumps(payload)
        except (TypeError, ValueError) as e:
            _logger.warning(
                f"Payload serialization failed for topic '{normalized_name}': {e}. "
                f"Using empty payload. FSM Instance: {self.id}"
            )
            payload_str = '{}'
        
        # Asynchronously notify each subscriber
        # Using numa_asynch_exec to ensure non-blocking delivery
        notified_count = 0
        for subscription in subscriptions:
            subscriber = subscription.subscriber_fsm_id
            if not subscriber.exists():
                _logger.warning(
                    f"Subscriber FSM instance {subscription.subscriber_fsm_id.id} "
                    f"does not exist. Skipping."
                )
                continue
            
            try:
                # Enqueue async notification
                subscriber.asynch_exec().notify(normalized_name, payload_str)
                notified_count += 1
                _logger.debug(
                    f"Enqueued notification to FSM instance {subscriber.id} "
                    f"for topic '{normalized_name}'"
                )
            except Exception as e:
                _logger.error(
                    f"Failed to enqueue notification to FSM instance {subscriber.id} "
                    f"for topic '{normalized_name}': {e}",
                    exc_info=True
                )
        
        _logger.info(
            f"Published to topic '{normalized_name}' from FSM instance {self.id}. "
            f"Notified {notified_count} subscribers."
        )
        
        return notified_count

    def notify(self, topic_name, payload_str):
        """
        Receive a notification (the Actor's inbox/router).
        
        This is the "Single Entry Point" for the Actor. It implements a dynamic
        dispatcher pattern:
        
        1. Logs the arrival of the message
        2. Tries to find a topic-specific handler method: `_handle_topic_{topic_name}`
        3. If handler exists, executes it with the payload
        4. Falls back to triggering an FSM event/transition with the topic name
        5. Robust error handling to prevent breaking the main thread
        
        :param topic_name: Name of the topic (normalized)
        :param payload_str: JSON string containing the payload
        
        Example:
            instance.notify('sale_order_confirmed', '{"order_id": 123}')
        """
        self.ensure_one()
        
        _logger.debug(
            f"FSM Instance {self.id} received notification for topic '{topic_name}'"
        )
        
        # Update subscription statistics if this instance is subscribed
        subscription = self.env['numa.fsm.subscription'].search([
            ('subscriber_fsm_id', '=', self.id),
            ('topic_id.name', '=', topic_name),
            ('is_active', '=', True)
        ], limit=1)
        if subscription:
            subscription.mark_notification_received()
        
        # Parse payload
        try:
            if isinstance(payload_str, str):
                payload = json.loads(payload_str) if payload_str else {}
            else:
                payload = payload_str or {}
        except (json.JSONDecodeError, TypeError) as e:
            _logger.warning(
                f"Failed to parse payload for topic '{topic_name}' in FSM instance {self.id}: {e}. "
                f"Using empty payload."
            )
            payload = {}
        
        # Dynamic Dispatcher: Try to find topic-specific handler
        handler_method_name = f'_handle_topic_{topic_name}'
        handler_method = getattr(self, handler_method_name, None)
        
        if handler_method and callable(handler_method):
            try:
                _logger.debug(
                    f"FSM Instance {self.id}: Found handler '{handler_method_name}'. Executing."
                )
                result = handler_method(payload)
                _logger.debug(
                    f"FSM Instance {self.id}: Handler '{handler_method_name}' executed successfully."
                )
                return result
            except Exception as e:
                _logger.error(
                    f"FSM Instance {self.id}: Handler '{handler_method_name}' failed: {e}",
                    exc_info=True
                )
                # Don't re-raise: continue to fallback
        else:
            _logger.debug(
                f"FSM Instance {self.id}: No handler '{handler_method_name}' found. "
                f"Trying FSM event fallback."
            )
        
        # Fallback: Try to trigger an FSM event/transition with the topic name
        # This unifies network events with state events
        try:
            if self.state in ['running', 'paused']:
                _logger.debug(
                    f"FSM Instance {self.id}: Attempting to send event '{topic_name}' to FSM."
                )
                # Try to send the event to the FSM
                # send_event expects a dict with 'name' key
                if hasattr(self, 'send_event'):
                    self.send_event({'name': topic_name, 'payload': payload})
                else:
                    _logger.debug(
                        f"FSM Instance {self.id}: No 'send_event' method available. "
                        f"Event '{topic_name}' not processed."
                    )
            else:
                _logger.debug(
                    f"FSM Instance {self.id}: FSM is in state '{self.state}'. "
                    f"Event '{topic_name}' not processed."
                )
        except Exception as e:
            _logger.error(
                f"FSM Instance {self.id}: Failed to process event '{topic_name}' via FSM: {e}",
                exc_info=True
            )
            # Don't re-raise: error handling should be robust
        
        # If we reach here, the message was received but not processed
        # This is acceptable in Schema-on-Read: the message was delivered
        _logger.info(
            f"FSM Instance {self.id}: Notification for topic '{topic_name}' received and logged. "
            f"No specific handler found."
        )
        return True

    def _handle_topic_test_ping(self, payload):
        """
        Example handler for 'test_ping' topic.
        
        This demonstrates how to implement topic-specific handlers.
        Simply writes a message to the FSM's chatter.
        
        :param payload: Dictionary containing the message payload
        :return: True on success
        """
        self.ensure_one()
        
        message = f"Pong recibido desde topic 'test_ping'"
        if payload:
            message += f" con payload: {json.dumps(payload, indent=2)}"
        
        self.message_post(body=f"<p>{message}</p>")
        _logger.info(f"FSM Instance {self.id}: {message}")
        
        return True

    def _handle_topic_system_ping(self, payload):
        """
        Handler for 'system.ping' topic.
        
        Diagnostic handler to verify connectivity between FSM instances.
        Writes a PONG message to the FSM's chatter with sender information.
        
        :param payload: Dictionary containing the message payload
        :return: True on success
        """
        self.ensure_one()
        
        # Extract sender information from payload
        sender = payload.get('sender', 'Unknown')
        timestamp = payload.get('timestamp', 'N/A')
        
        # Build the message
        message_body = f"🏓 <strong>PONG recibido desde {sender}!</strong><br/>"
        message_body += f"<small>Timestamp: {timestamp}</small><br/>"
        
        if payload:
            # Include full payload for debugging
            payload_str = json.dumps(payload, indent=2, ensure_ascii=False)
            message_body += f"<pre>{payload_str}</pre>"
        
        # Post to chatter
        self.message_post(body=message_body)
        
        _logger.info(
            f"FSM Instance {self.id}: PONG recibido desde {sender} "
            f"(Topic: system.ping)"
        )
        
        return True
