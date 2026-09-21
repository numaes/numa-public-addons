# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# A topic name is an identifier: lowercase letters, digits and underscores. Anything a
# Python attribute name cannot hold cannot be a topic, because the dispatcher builds a
# method name out of it (`_handle_topic_<name>`).
TOPIC_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$')


class FsmTopic(models.Model):
    """The semantic contract of an event.

    It exists for governance, documentation and context, not for runtime validation:
    the transport does not check the payload, the receiver does. A message whose topic
    is not declared here is still delivered -- the topic may be declared later.
    """
    _name = 'numa.fsm.topic'
    _description = 'FSM Pub/Sub Topic'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Topic Name',
        required=True,
        index=True,
        help="Identifier of the topic, e.g. 'sale_order_confirmed': lowercase letters, "
             "digits and underscores, starting with a letter.")
    description = fields.Text(
        string='Description',
        help="What this topic means and when it is published. Also the context an AI "
             "reads when asked about the system's events.")
    payload_example = fields.Text(
        string='Payload Example',
        help="An example of the payload, as JSON. Documentation, not validation.")
    active = fields.Boolean(
        string='Active', default=True,
        help="An inactive topic accepts no new subscriptions and publishes nothing.")
    subscription_ids = fields.One2many(
        'numa.fsm.subscription', 'topic_id', string='Subscription Lines')
    subscription_count = fields.Integer(
        string='Subscriptions', compute='_compute_subscription_count',
        help="How many active subscriptions this topic has.")

    # [20.0] Was `_sql_constraints`, which Odoo 20 ignores with a warning
    # (model_classes.py:175). The unique index it was supposed to create did not exist,
    # so two topics could share a name and a publisher would find whichever came first.
    _name_unique = models.UniqueIndex(
        '(name)', "A topic name identifies one topic, and this one is already taken.")

    @api.depends('subscription_ids.is_active')
    def _compute_subscription_count(self):
        """[20.0] Over the one2many, in one query for the whole recordset.

        It used to run a `search_count` per record and depend on `name`, which is not
        what it reads: adding a subscription did not refresh the number.
        """
        counted = {
            topic.id: count
            for topic, count in self.env['numa.fsm.subscription']._read_group(
                [('topic_id', 'in', self.ids), ('is_active', '=', True)],
                groupby=['topic_id'], aggregates=['__count'])
        }
        for topic in self:
            topic.subscription_count = counted.get(topic.id, 0)

    @api.constrains('name')
    def _check_name_format(self):
        for topic in self:
            if topic.name and not TOPIC_NAME_RE.match(topic.name):
                raise ValidationError(_(
                    "A topic name is an identifier: lowercase letters, digits and "
                    "underscores, starting with a letter. The dispatcher builds a method "
                    "name out of it, so a dot or a space has nowhere to go.\n\n"
                    "Name: %(name)s\nSuggested: %(suggested)s",
                    name=topic.name, suggested=self.normalize_topic_name(topic.name)))

    @api.model
    def normalize_topic_name(self, topic_name):
        """Fold a name into the shape a topic name has.

        [20.0] Dots fold to underscores now. They did not, and the module's own data
        declared `system.ping`: the constraint rejected it, so the module could not
        install, and had the constraint let it through the dispatcher would have looked
        for a method called `_handle_topic_system.ping`, which cannot exist.
        """
        if not topic_name:
            return ''
        folded = topic_name.strip().lower()
        folded = re.sub(r'[\s.\-]+', '_', folded)
        return re.sub(r'[^a-z0-9_]', '', folded)
