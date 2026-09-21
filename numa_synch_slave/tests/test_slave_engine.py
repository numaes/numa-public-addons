"""What the Slave sends, and what it does with the answer."""

from unittest.mock import patch

from odoo.tests import tagged

from .common import FakeResponse, SlaveSynchCase

POST = 'odoo.addons.numa_synch_slave.models.numa_synch_engine.requests.post'


@tagged('post_install', '-at_install')
class TestSlaveEngine(SlaveSynchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rule_partner = cls._rule('res.partner')

    # ------------------------------------------------------------------
    # Batching
    # ------------------------------------------------------------------

    def test_01_batches_respect_the_configured_size(self):
        batches = self.engine._create_batches(list(range(25)), 10)

        self.assertEqual([len(b) for b in batches], [10, 10, 5])

    def test_02_nothing_to_send_is_no_batches(self):
        self.assertEqual(self.engine._create_batches([], 10), [])

    # ------------------------------------------------------------------
    # The wire
    # ------------------------------------------------------------------

    def test_03_a_batch_is_posted_flat_with_the_api_key(self):
        """The Slave speaks flat JSON, which is what the Master now listens for."""
        connection = self._connection()
        batch = [{'model': 'res.partner', 'local_id': 5,
                  'vals': {'name': 'A'}, 'write_date': None}]
        answer = {'status': 'success', 'updated_mappings': []}

        with patch(POST, return_value=FakeResponse(200, answer)) as post:
            sent = self.engine._send_batch(connection, batch, 1)

        self.assertTrue(sent)
        args, kwargs = post.call_args
        self.assertEqual(args[0],
                         'https://master.example.com/numa_synch/api/v1/sync_batch')
        self.assertEqual(kwargs['json']['slave_token'], connection.slave_token)
        self.assertEqual(kwargs['json']['records'], batch)
        self.assertNotIn('params', kwargs['json'])
        self.assertEqual(kwargs['headers']['Authorization'],
                         'Bearer %s' % connection.api_key)

    def test_04_metadata_travels_with_the_first_batch_only(self):
        """It describes the schema, and the schema does not change mid-cycle."""
        connection = self._connection()
        batch = [{'model': 'res.partner', 'local_id': 5, 'vals': {}}]
        metadata = {'system': {}, 'models': {}}
        answer = {'status': 'success', 'updated_mappings': []}

        with patch(POST, return_value=FakeResponse(200, answer)) as post:
            self.engine._send_batch(connection, batch, 1, metadata)
            self.engine._send_batch(connection, batch, 2, metadata)

        self.assertIn('meta', post.call_args_list[0].kwargs['json'])
        self.assertNotIn('meta', post.call_args_list[1].kwargs['json'])

    def test_05_an_error_body_is_a_failed_batch(self):
        connection = self._connection()
        batch = [{'model': 'res.partner', 'local_id': 5, 'vals': {}}]
        answer = {'status': 'error', 'message': 'Model not allowed',
                  'updated_mappings': []}

        with patch(POST, return_value=FakeResponse(200, answer)):
            self.assertFalse(self.engine._send_batch(connection, batch, 1))

    def test_06_an_http_error_is_a_failed_batch(self):
        connection = self._connection()
        batch = [{'model': 'res.partner', 'local_id': 5, 'vals': {}}]

        with patch(POST, return_value=FakeResponse(500, {}, text='boom')):
            self.assertFalse(self.engine._send_batch(connection, batch, 1))

    def test_07_an_unreachable_master_is_a_failed_batch_not_a_crash(self):
        """A Slave is offline-first: a network that is down is an ordinary day."""
        import requests

        connection = self._connection()
        batch = [{'model': 'res.partner', 'local_id': 5, 'vals': {}}]

        with patch(POST, side_effect=requests.exceptions.ConnectionError('down')):
            self.assertFalse(self.engine._send_batch(connection, batch, 1))

    # ------------------------------------------------------------------
    # The answer
    # ------------------------------------------------------------------

    def test_08_returned_ids_become_mappings(self):
        """This is what stops the next cycle from sending the record again."""
        connection = self._connection()
        partner = self.env['res.partner'].create({'name': 'Mapped'})
        answer = {
            'status': 'success',
            'updated_mappings': [
                {'model': 'res.partner', 'slave_id': partner.id, 'master_id': 909},
            ],
        }

        self.engine._process_batch_response([], answer, connection)

        self.assertEqual(
            self.env['numa.synch.map'].get_remote_id(
                'res.partner', partner.id, 'MASTER'),
            909)

    def test_09_a_malformed_mapping_is_skipped_not_fatal(self):
        connection = self._connection()
        partner = self.env['res.partner'].create({'name': 'Mapped'})
        answer = {'updated_mappings': [
            {'model': 'res.partner', 'slave_id': None, 'master_id': 1},
            {'model': 'res.partner', 'slave_id': partner.id, 'master_id': 910},
        ]}

        self.engine._process_batch_response([], answer, connection)

        self.assertEqual(
            self.env['numa.synch.map'].get_remote_id(
                'res.partner', partner.id, 'MASTER'),
            910)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def test_10_an_unmapped_record_needs_syncing(self):
        connection = self._connection()
        partner = self.env['res.partner'].create({'name': 'New Here'})

        self.assertTrue(
            self.engine._record_needs_sync('res.partner', partner, connection))

    def test_11_a_record_untouched_since_the_last_sync_does_not(self):
        partner = self.env['res.partner'].create({'name': 'Settled'})
        self.env['numa.synch.map'].set_mapping(
            'res.partner', partner.id, 500, 'MASTER',
            last_sync_date=partner.write_date)
        connection = self._connection(last_sync_date=partner.write_date)

        self.assertFalse(
            self.engine._record_needs_sync('res.partner', partner, connection))

    def test_12_only_models_with_a_rule_are_discovered(self):
        connection = self._connection()
        self.env['res.partner'].create({'name': 'Discovered'})

        discovered = self.engine._discover_records(connection)

        self.assertTrue(discovered)
        self.assertEqual({r._name for r in discovered}, {'res.partner'})

    def test_13_an_inactive_connection_sends_nothing(self):
        connection = self._connection()
        connection.write({'active': False})

        with patch(POST) as post:
            self.engine.run_synchronization_cycle(connection)

        post.assert_not_called()

    # ------------------------------------------------------------------
    # A whole cycle
    # ------------------------------------------------------------------

    def test_14_a_successful_cycle_records_when_it_ran(self):
        """`last_sync_date` is the delta detector's only memory.

        Moving it on a failed cycle would silently drop everything that cycle was
        carrying, so it moves only when every batch was accepted.
        """
        connection = self._connection()
        self.env['res.partner'].create({'name': 'To Send'})
        answer = {'status': 'success', 'updated_mappings': []}

        with patch(POST, return_value=FakeResponse(200, answer)):
            self.engine.run_synchronization_cycle(connection)

        self.assertTrue(connection.last_sync_date)

    def test_15_a_failed_cycle_does_not_move_the_marker(self):
        from odoo.exceptions import UserError

        connection = self._connection()
        self.env['res.partner'].create({'name': 'To Send'})
        answer = {'status': 'error', 'message': 'refused'}

        with patch(POST, return_value=FakeResponse(200, answer)):
            with self.assertRaises(UserError):
                self.engine.run_synchronization_cycle(connection)

        self.assertFalse(connection.last_sync_date)
