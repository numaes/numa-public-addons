# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class FsmSubscription(models.Model):
    """The wiring of the graph: this FSM instance listens to that topic."""
    _name = 'numa.fsm.subscription'
    _description = 'FSM Pub/Sub Subscription'
    _order = 'topic_id, create_date desc'

    topic_id = fields.Many2one(
        'numa.fsm.topic', string='Topic', required=True, ondelete='cascade', index=True,
        help="The topic this subscription listens to.")
    subscriber_fsm_id = fields.Many2one(
        'fsm.instance', string='Subscriber FSM Instance', required=True,
        ondelete='cascade', index=True,
        help="The FSM instance that receives what is published to the topic.")
    is_active = fields.Boolean(
        string='Active', default=True, index=True,
        help="An inactive subscription receives nothing.")
    last_notification_date = fields.Datetime(
        string='Last Notification', readonly=True, copy=False,
        help="When something last arrived through this subscription.")
    notification_count = fields.Integer(
        string='Notifications Count', default=0, readonly=True, copy=False,
        help="How many notifications arrived through this subscription.")

    # [20.0] Was `_sql_constraints`, which Odoo 20 ignores with a warning
    # (model_classes.py:175). Without the index a topic could be subscribed twice by the
    # same instance, and every publication would be delivered to it twice.
    _topic_subscriber_unique = models.UniqueIndex(
        '(topic_id, subscriber_fsm_id)',
        "This FSM instance is already subscribed to that topic.")

    @api.constrains('is_active', 'topic_id')
    def _check_active_topic(self):
        """An active subscription to an inactive topic is wiring to nowhere.

        [20.0] The constraint reads `is_active` and did not depend on it, so switching a
        subscription back on against a closed topic went through.
        """
        for subscription in self:
            if subscription.is_active and not subscription.topic_id.active:
                raise ValidationError(_(
                    "Topic '%(topic)s' is inactive: a subscription to it cannot be active.",
                    topic=subscription.topic_id.name))

    def mark_notification_received(self):
        """Record that something arrived. Called from the subscriber's inbox."""
        self.ensure_one()
        self.write({
            'last_notification_date': fields.Datetime.now(),
            'notification_count': self.notification_count + 1,
        })
