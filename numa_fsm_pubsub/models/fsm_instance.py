# -*- coding: utf-8 -*-
"""The actor side: an FSM instance publishes to topics and receives from them."""
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class FsmInstance(models.Model):
    _inherit = 'fsm.instance'

    subscription_ids = fields.One2many(
        'numa.fsm.subscription', 'subscriber_fsm_id', string='Subscription Lines')
    subscription_count = fields.Integer(
        string='Active Subscriptions', compute='_compute_subscription_count',
        help="How many topics this instance is listening to.")

    @api.depends('subscription_ids.is_active')
    def _compute_subscription_count(self):
        """[20.0] One query for the recordset, and a depends that names what it reads.

        It used to run a `search_count` per record with no `@api.depends` at all, so the
        number was computed once and never refreshed.
        """
        counted = {
            instance.id: count
            for instance, count in self.env['numa.fsm.subscription']._read_group(
                [('subscriber_fsm_id', 'in', self.ids), ('is_active', '=', True)],
                groupby=['subscriber_fsm_id'], aggregates=['__count'])
        }
        for instance in self:
            instance.subscription_count = counted.get(instance.id, 0)

    # ------------------------------------------------------------------
    # Publisher
    # ------------------------------------------------------------------

    def publish(self, topic_name, payload=None):
        """Publish an event to a topic, and hand it to every active subscriber.

        Delivery is asynchronous: each subscriber gets a background job, so a slow or
        failing subscriber does not hold up the publisher or the transaction that
        triggered it.

        A topic that is not declared is not an error. The transport does not validate --
        that is the whole point of schema-on-read -- but with nothing declared there is
        nobody subscribed either, so the call is logged and returns 0.

        :return: how many subscribers were handed the message
        """
        self.ensure_one()

        Topic = self.env['numa.fsm.topic']
        normalized_name = Topic.normalize_topic_name(topic_name)
        topic = Topic.search([('name', '=', normalized_name)], limit=1)
        if not topic:
            _logger.warning(
                "Topic %r is not declared, so nobody is subscribed to it; "
                "published from FSM instance %s and delivered to nobody.",
                normalized_name, self.id)
            return 0
        if not topic.active:
            _logger.warning("Topic %r is inactive; publication from FSM instance %s "
                            "delivered to nobody.", normalized_name, self.id)
            return 0

        subscriptions = topic.subscription_ids.filtered('is_active')
        if not subscriptions:
            _logger.debug("Topic %r has no active subscriptions; published from FSM "
                          "instance %s.", normalized_name, self.id)
            return 0

        payload_str = self._numa_serialize_payload(payload, normalized_name)

        notified = 0
        for subscription in subscriptions:
            subscriber = subscription.subscriber_fsm_id
            if not subscriber.exists():
                _logger.warning("Subscriber %s of topic %r no longer exists.",
                                subscription.subscriber_fsm_id.id, normalized_name)
                continue
            try:
                subscriber.asynch_exec().notify(normalized_name, payload_str)
                notified += 1
            except Exception:
                _logger.exception(
                    "Could not enqueue the notification to FSM instance %s for topic %r.",
                    subscriber.id, normalized_name)

        _logger.info("Published %r from FSM instance %s to %s subscriber(s).",
                     normalized_name, self.id, notified)
        return notified

    def _numa_serialize_payload(self, payload, topic_name):
        """The payload travels as a JSON string, because a job's arguments do."""
        if payload is None:
            return '{}'
        try:
            if isinstance(payload, str):
                json.loads(payload)   # a string must already be JSON
                return payload
            return json.dumps(payload)
        except (TypeError, ValueError) as error:
            _logger.warning(
                "The payload published to %r from FSM instance %s is not serializable "
                "(%s); an empty one is sent instead.", topic_name, self.id, error)
            return '{}'

    # ------------------------------------------------------------------
    # Subscriber: the inbox
    # ------------------------------------------------------------------

    def notify(self, topic_name, payload_str):
        """Receive a notification. This is the actor's single entry point.

        It dispatches in two steps:

        1. a method named ``_handle_topic_<topic>``, if the instance has one;
        2. failing that, an FSM event named after the topic, which is what unifies
           messages arriving from the network with events raised inside the machine.

        Neither step raises: a subscriber that breaks must not take down the publisher's
        job or the other subscribers. What went wrong is logged.
        """
        self.ensure_one()
        topic_name = self.env['numa.fsm.topic'].normalize_topic_name(topic_name)

        subscription = self.env['numa.fsm.subscription'].search([
            ('subscriber_fsm_id', '=', self.id),
            ('topic_id.name', '=', topic_name),
            ('is_active', '=', True),
        ], limit=1)
        if subscription:
            subscription.mark_notification_received()

        payload = self._numa_parse_payload(payload_str, topic_name)

        # [20.0] The handler is looked up under the NORMALIZED name. It was looked up
        # under the raw one, so the shipped `system.ping` topic asked for a method called
        # `_handle_topic_system.ping`, which no Python name can be.
        handler = getattr(self, '_handle_topic_%s' % topic_name, None)
        if callable(handler):
            try:
                return handler(payload)
            except Exception:
                _logger.exception("FSM instance %s: handler for topic %r failed.",
                                  self.id, topic_name)
                return False

        if self.fsm_state not in ('running', 'paused'):
            _logger.debug("FSM instance %s is %s; topic %r was delivered and not acted on.",
                          self.id, self.fsm_state, topic_name)
            return True

        try:
            self.send_event({'name': topic_name, 'payload': payload})
        except Exception:
            _logger.exception("FSM instance %s: event %r could not be processed.",
                              self.id, topic_name)
        return True

    def _numa_parse_payload(self, payload_str, topic_name):
        if not isinstance(payload_str, str):
            return payload_str or {}
        try:
            return json.loads(payload_str) if payload_str else {}
        except (json.JSONDecodeError, TypeError) as error:
            _logger.warning(
                "FSM instance %s: the payload of topic %r is not JSON (%s); "
                "an empty one is used.", self.id, topic_name, error)
            return {}

    # ------------------------------------------------------------------
    # Handlers shipped with the module
    # ------------------------------------------------------------------

    def _handle_topic_system_ping(self, payload):
        """Answer a diagnostic ping in the chatter.

        This is what tells an operator that the circuit works end to end: a publish, a
        background job, a delivery and a visible effect on another record.
        """
        self.ensure_one()
        sender = payload.get('sender', 'unknown')
        timestamp = payload.get('timestamp', 'n/a')
        body = ("<p><strong>PONG from %s</strong><br/><small>%s</small></p>"
                % (sender, timestamp))
        if payload:
            body += "<pre>%s</pre>" % json.dumps(payload, indent=2, ensure_ascii=False)
        self.message_post(body=body)
        _logger.info("FSM instance %s answered a ping from %s.", self.id, sender)
        return True
