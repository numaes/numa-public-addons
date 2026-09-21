# -*- coding: utf-8 -*-
"""Publishing, delivering and dispatching.

The module had no tests, and it could not be installed: its own data file declared a
topic called `system.ping`, which its own constraint rejects, so loading the module
failed. Everything below is therefore being checked against a running database for the
first time.

Delivery is asynchronous by design, so the tests split in two. The routing -- who would
be handed the message -- is asserted on `publish`'s return value and on the jobs it
leaves behind. What the message does on arrival is asserted by calling `notify`
directly, which is exactly what the worker calls.
"""
import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPubSub(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.definition = cls.env['fsm.definition'].create({'name': 'Pub/Sub'})
        Instance = cls.env['fsm.instance']
        cls.publisher = Instance.create({'definition_id': cls.definition.id})
        cls.subscriber = Instance.create({'definition_id': cls.definition.id})
        cls.other = Instance.create({'definition_id': cls.definition.id})
        cls.topic = cls.env['numa.fsm.topic'].create({
            'name': 'order_confirmed', 'description': 'An order was confirmed.'})

    def _subscribe(self, instance, topic=None, active=True):
        return self.env['numa.fsm.subscription'].create({
            'topic_id': (topic or self.topic).id,
            'subscriber_fsm_id': instance.id,
            'is_active': active,
        })

    # ------------------------------------------------------------------
    # Topic names
    # ------------------------------------------------------------------

    def test_01_a_topic_name_is_an_identifier(self):
        """A dot has nowhere to go: the dispatcher builds a method name out of the topic.
        The module shipped `system.ping` and its own constraint rejected it, which is why
        it could not install."""
        with self.assertRaises(ValidationError):
            self.env['numa.fsm.topic'].create({'name': 'system.ping'})
        with self.assertRaises(ValidationError):
            self.env['numa.fsm.topic'].create({'name': 'Order Confirmed'})

    def test_02_normalising_folds_what_it_can(self):
        Topic = self.env['numa.fsm.topic']
        self.assertEqual(Topic.normalize_topic_name('system.ping'), 'system_ping')
        self.assertEqual(Topic.normalize_topic_name(' Order Confirmed '), 'order_confirmed')
        self.assertEqual(Topic.normalize_topic_name('sale-order'), 'sale_order')
        self.assertEqual(Topic.normalize_topic_name(''), '')

    def test_03_a_topic_name_is_unique(self):
        """The uniqueness was declared with `_sql_constraints`, which Odoo 20 ignores
        with a warning, so the index did not exist and two topics could share a name."""
        with self.assertRaises(Exception):
            self.env['numa.fsm.topic'].create({'name': 'order_confirmed'})
            self.env.flush_all()

    def test_04_the_shipped_topics_exist(self):
        """They could not be created before: see test_01."""
        nombres = self.env['numa.fsm.topic'].search([]).mapped('name')
        self.assertIn('system_ping', nombres)
        self.assertIn('test_ping', nombres)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def test_05_a_pair_subscribes_once(self):
        """Also `_sql_constraints`, also absent. A double subscription means every
        publication is delivered twice."""
        self._subscribe(self.subscriber)
        with self.assertRaises(Exception):
            self._subscribe(self.subscriber)
            self.env.flush_all()

    def test_06_an_active_subscription_needs_an_active_topic(self):
        cerrado = self.env['numa.fsm.topic'].create({'name': 'closed', 'active': False})
        with self.assertRaises(ValidationError):
            self._subscribe(self.subscriber, topic=cerrado)

    def test_07_reactivating_against_a_closed_topic_is_refused(self):
        """The constraint read `is_active` without depending on it, so switching a
        subscription back on went through unchecked."""
        suscripcion = self._subscribe(self.subscriber, active=True)
        suscripcion.is_active = False
        self.topic.active = False
        with self.assertRaises(ValidationError):
            suscripcion.is_active = True

    def test_08_the_counters_say_what_they_read(self):
        """Both counts used to be computed with no `@api.depends` on the subscriptions,
        so they never refreshed."""
        self.assertEqual(self.topic.subscription_count, 0)
        self.assertEqual(self.subscriber.subscription_count, 0)
        suscripcion = self._subscribe(self.subscriber)
        self.assertEqual(self.topic.subscription_count, 1)
        self.assertEqual(self.subscriber.subscription_count, 1)
        suscripcion.is_active = False
        self.assertEqual(self.topic.subscription_count, 0)
        self.assertEqual(self.subscriber.subscription_count, 0)

    # ------------------------------------------------------------------
    # Publishing: who gets handed the message
    # ------------------------------------------------------------------

    def test_09_publishing_reaches_the_active_subscribers(self):
        self._subscribe(self.subscriber)
        self._subscribe(self.other, active=False)
        self.assertEqual(self.publisher.publish('order_confirmed', {'id': 1}), 1)

    def test_10_an_undeclared_topic_reaches_nobody(self):
        """Not an error: the transport does not validate. But with nothing declared
        there is nobody subscribed either."""
        self.assertEqual(self.publisher.publish('never_declared', {}), 0)

    def test_11_an_inactive_topic_reaches_nobody(self):
        self._subscribe(self.subscriber)
        self.topic.subscription_ids.is_active = False
        self.topic.active = False
        self.assertEqual(self.publisher.publish('order_confirmed', {}), 0)

    def test_12_the_name_is_normalised_on_the_way_out(self):
        """Publishing 'Order Confirmed' finds the topic 'order_confirmed'."""
        self._subscribe(self.subscriber)
        self.assertEqual(self.publisher.publish('Order Confirmed', {}), 1)

    def test_13_a_payload_that_cannot_be_serialised_does_not_stop_the_publication(self):
        self._subscribe(self.subscriber)
        self.assertEqual(self.publisher.publish('order_confirmed', {'x': object()}), 1)

    def test_14_a_string_payload_must_already_be_json(self):
        serialise = self.publisher._numa_serialize_payload
        self.assertEqual(serialise('{"a": 1}', 't'), '{"a": 1}')
        self.assertEqual(serialise('not json', 't'), '{}')
        self.assertEqual(serialise(None, 't'), '{}')
        self.assertEqual(json.loads(serialise({'a': 1}, 't')), {'a': 1})

    # ------------------------------------------------------------------
    # Receiving: what the worker calls
    # ------------------------------------------------------------------

    def test_15_the_handler_is_found_under_the_normalised_name(self):
        """`_handle_topic_system_ping` was unreachable: the lookup used the raw topic
        name, so the shipped `system.ping` asked for `_handle_topic_system.ping`."""
        antes = len(self.subscriber.message_ids)
        self.subscriber.notify('system.ping', json.dumps({'sender': 'test'}))
        self.assertGreater(len(self.subscriber.message_ids), antes)
        self.assertIn('PONG', self.subscriber.message_ids[0].body)

    def test_16_receiving_updates_the_subscription_statistics(self):
        suscripcion = self._subscribe(self.subscriber)
        self.subscriber.notify('order_confirmed', '{}')
        self.assertEqual(suscripcion.notification_count, 1)
        self.assertTrue(suscripcion.last_notification_date)

    def test_17_a_broken_payload_does_not_break_the_delivery(self):
        suscripcion = self._subscribe(self.subscriber)
        self.assertTrue(self.subscriber.notify('order_confirmed', 'not json at all'))
        self.assertEqual(suscripcion.notification_count, 1)

    def test_18_a_failing_handler_does_not_propagate(self):
        """One subscriber breaking must not take down the publisher's job, nor the
        other subscribers. The shipped handler is made to raise, which is the closest
        thing to a subscriber with a bug in it."""
        def explota(records, payload):
            raise RuntimeError('boom')
        self.patch(type(self.subscriber), '_handle_topic_system_ping', explota)
        with self.assertLogs('odoo.addons.numa_fsm_pubsub.models.fsm_instance',
                             level='ERROR'):
            self.assertFalse(self.subscriber.notify('system_ping', '{}'))

    def test_19_without_a_handler_it_becomes_an_fsm_event(self):
        """What unifies a message from the network with an event raised inside the
        machine. An instance that is not running is delivered to and left alone."""
        recibidos = []
        self.patch(type(self.subscriber), 'send_event',
                   lambda records, event: recibidos.append(event))
        self.subscriber.fsm_state = 'running'
        self.subscriber.notify('order_confirmed', json.dumps({'id': 7}))
        self.assertEqual(recibidos, [{'name': 'order_confirmed', 'payload': {'id': 7}}])

        recibidos.clear()
        self.subscriber.fsm_state = 'ended'
        self.subscriber.notify('order_confirmed', '{}')
        self.assertEqual(recibidos, [])
