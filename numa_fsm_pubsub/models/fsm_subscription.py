# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class FsmSubscription(models.Model):
    """
    Defines the wiring (cableado) of the graph.
    
    Represents a subscription relationship where an FSM instance listens to a specific topic.
    """
    _name = 'numa.fsm.subscription'
    _description = 'FSM Pub/Sub Subscription'
    _order = 'topic_id, create_date desc'

    topic_id = fields.Many2one(
        'numa.fsm.topic',
        string='Topic',
        required=True,
        ondelete='cascade',
        index=True,
        help="The topic this subscription listens to"
    )
    subscriber_fsm_id = fields.Many2one(
        'fsm.instance',
        string='Subscriber FSM Instance',
        required=True,
        ondelete='cascade',
        index=True,
        help="The FSM instance that will receive notifications for this topic"
    )
    is_active = fields.Boolean(
        string='Active',
        default=True,
        index=True,
        help="If unchecked, this subscription will not receive notifications"
    )
    last_notification_date = fields.Datetime(
        string='Last Notification',
        readonly=True,
        help="Timestamp of the last notification received via this subscription"
    )
    notification_count = fields.Integer(
        string='Notifications Count',
        default=0,
        readonly=True,
        help="Total number of notifications received via this subscription"
    )

    _sql_constraints = [
        ('topic_subscriber_uniq', 'unique(topic_id, subscriber_fsm_id)',
         'A subscription for this topic and FSM instance already exists!'),
    ]

    @api.constrains('topic_id', 'subscriber_fsm_id')
    def _check_subscription(self):
        """Ensure topic is active if subscription is active."""
        for subscription in self:
            if subscription.is_active and not subscription.topic_id.active:
                raise ValidationError(
                    f"Cannot activate subscription to inactive topic '{subscription.topic_id.name}'"
                )

    def mark_notification_received(self):
        """Update statistics when a notification is received."""
        self.ensure_one()
        self.write({
            'last_notification_date': fields.Datetime.now(),
            'notification_count': self.notification_count + 1,
        })
