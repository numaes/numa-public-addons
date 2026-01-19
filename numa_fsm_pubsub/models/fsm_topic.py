# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import json

class FsmTopic(models.Model):
    """
    Defines the semantic "Contract" of an event.
    
    Purpose: Governance, Documentation, and Context for AI (not for strict runtime validation).
    This follows the "Schema-on-Read" philosophy where the transport mechanism doesn't validate
    data; validation occurs at the receiving end.
    """
    _name = 'numa.fsm.topic'
    _description = 'FSM Pub/Sub Topic'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Topic Name',
        required=True,
        index=True,
        help="Unique identifier for the topic (e.g., 'sale_order_confirmed'). "
             "Should be lowercase, no spaces. Use underscores for separation."
    )
    description = fields.Text(
        string='Description',
        help="Human-readable description of what this topic represents. "
             "Also used for RAG (Retrieval-Augmented Generation) in AI contexts."
    )
    payload_example = fields.Text(
        string='Payload Example',
        help="Example JSON structure of the expected payload. "
             "Used for documentation and AI context, not for runtime validation."
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help="If unchecked, this topic will not be available for new subscriptions."
    )
    subscription_count = fields.Integer(
        string='Subscriptions',
        compute='_compute_subscription_count',
        help="Number of active subscriptions to this topic"
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Topic name must be unique!'),
    ]

    @api.depends('name')
    def _compute_subscription_count(self):
        """Compute the number of active subscriptions for each topic."""
        for topic in self:
            topic.subscription_count = self.env['numa.fsm.subscription'].search_count([
                ('topic_id', '=', topic.id),
                ('is_active', '=', True)
            ])

    @api.constrains('name')
    def _check_name_format(self):
        """Ensure topic name follows naming conventions."""
        for topic in self:
            if not topic.name:
                continue
            # Normalize and check: should be lowercase, alphanumeric with underscores
            normalized = topic.name.lower().strip().replace(' ', '_')
            if normalized != topic.name:
                raise ValidationError(
                    f"Topic name '{topic.name}' should be lowercase with underscores. "
                    f"Suggested: '{normalized}'"
                )
            if not topic.name.replace('_', '').replace('-', '').isalnum():
                raise ValidationError(
                    f"Topic name '{topic.name}' should only contain alphanumeric characters, "
                    f"underscores, and hyphens."
                )

    def normalize_topic_name(self, topic_name):
        """
        Normalize topic name to avoid common errors.
        
        :param topic_name: Raw topic name
        :return: Normalized topic name (lowercase, underscores instead of spaces)
        """
        if not topic_name:
            return ''
        return topic_name.lower().strip().replace(' ', '_').replace('-', '_')
