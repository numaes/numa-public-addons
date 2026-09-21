"""The connection record: its own cron, its own validation, its own handshake."""

from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import FakeResponse, SlaveSynchCase

POST = 'odoo.addons.numa_synch_slave.models.numa_synch_connection.requests.post'


@tagged('post_install', '-at_install')
class TestConnection(SlaveSynchCase):

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def test_01_several_connections_are_created_at_once(self):
        """`create` takes a list, and this override did not.

        It was declared `@api.model def create(self, vals)`. Odoo 20 has no shim
        left for that, so the list arrived where a dict was expected and
        `vals['slave_token'] = ...` died with "list indices must be integers".
        Creating one at a time worked, which is why it went unnoticed -- until an
        import or a multi-record copy tried.
        """
        connections = self.Connection.create([
            {'name': 'A', 'master_url': 'https://a.example.com',
             'master_db': 'a', 'api_key': 'k'},
            {'name': 'B', 'master_url': 'https://b.example.com',
             'master_db': 'b', 'api_key': 'k'},
        ])

        self.assertEqual(len(connections), 2)
        self.assertEqual(len(set(connections.mapped('slave_token'))), 2)
        self.assertTrue(all(connections.mapped('cron_id')))

    def test_02_every_connection_gets_its_own_token(self):
        first = self._connection(name='First')
        second = self._connection(name='Second')

        self.assertTrue(first.slave_token)
        self.assertNotEqual(first.slave_token, second.slave_token)

    def test_03_a_given_token_is_kept(self):
        connection = self._connection(slave_token='a-token-we-already-had')

        self.assertEqual(connection.slave_token, 'a-token-we-already-had')

    # ------------------------------------------------------------------
    # The cron
    # ------------------------------------------------------------------

    def test_04_a_connection_brings_its_cron(self):
        """And the cron must be creatable at all.

        `ir.cron` lost `numbercall` and `doall` in 20.0, and this method passed
        both, so every connection created here raised on its own cron.
        """
        connection = self._connection(sync_interval_number=7,
                                      sync_interval_type='hours')

        cron = connection.cron_id
        self.assertTrue(cron)
        self.assertEqual(cron.interval_number, 7)
        self.assertEqual(cron.interval_type, 'hours')
        self.assertIn(str(connection.id), cron.code)

    def test_05_changing_the_interval_moves_the_cron(self):
        connection = self._connection()
        connection.write({'sync_interval_number': 30,
                          'sync_interval_type': 'minutes'})

        self.assertEqual(connection.cron_id.interval_number, 30)
        self.assertEqual(connection.cron_id.interval_type, 'minutes')

    def test_06_deactivating_the_connection_deactivates_the_cron(self):
        connection = self._connection()
        connection.write({'active': False})

        self.assertFalse(connection.cron_id.active)

    def test_07_deleting_the_connection_deletes_the_cron(self):
        connection = self._connection()
        cron = connection.cron_id
        connection.unlink()

        self.assertFalse(cron.exists())

    def test_08_a_scheduled_time_sets_the_next_call(self):
        connection = self._connection(use_scheduled_time=True,
                                      sync_schedule_time=3.5)

        nextcall = connection.cron_id.nextcall
        self.assertTrue(nextcall)
        self.assertEqual((nextcall.hour, nextcall.minute), (3, 30))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def test_09_the_master_url_must_be_a_url(self):
        with self.assertRaises(ValidationError):
            self._connection(master_url='master.example.com')

    def test_10_the_batch_size_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._connection(batch_size=0)

    def test_11_the_interval_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._connection(sync_interval_number=0)

    def test_12_the_scheduled_time_must_be_a_time_of_day(self):
        with self.assertRaises(ValidationError):
            self._connection(use_scheduled_time=True, sync_schedule_time=25.0)

    # ------------------------------------------------------------------
    # Test Connection
    # ------------------------------------------------------------------

    def test_13_a_reachable_master_reports_success(self):
        connection = self._connection()
        body = {'status': 'success', 'message': 'No records to process',
                'updated_mappings': []}

        with patch(POST, return_value=FakeResponse(200, body)):
            with self.assertRaises(UserError) as caught:
                connection.action_test_connection()

        self.assertIn('successful', str(caught.exception))

    def test_14_a_refusal_is_not_reported_as_success(self):
        """The Master returns its refusals with HTTP 200 and an error body.

        This read the status code alone, so a rejected token, an unknown model and
        a mismatched schema all came back to the operator as "Connection test
        successful!" -- and the first real batch then failed with nothing to point at.
        """
        connection = self._connection()
        body = {'status': 'error', 'message': 'slave_token is required',
                'updated_mappings': []}

        with patch(POST, return_value=FakeResponse(200, body)):
            with self.assertRaises(UserError) as caught:
                connection.action_test_connection()

        message = str(caught.exception)
        self.assertNotIn('successful', message)
        self.assertIn('slave_token is required', message)

    def test_15_an_answer_that_is_not_json_says_so(self):
        """A URL that points at something else answers HTML, not JSON."""
        connection = self._connection()

        with patch(POST, return_value=FakeResponse(
                200, None, text='<html>Odoo</html>')):
            with self.assertRaises(UserError) as caught:
                connection.action_test_connection()

        self.assertNotIn('successful', str(caught.exception))

    def test_16_a_rejected_key_is_named_as_such(self):
        connection = self._connection()

        with patch(POST, return_value=FakeResponse(401, {})):
            with self.assertRaises(UserError) as caught:
                connection.action_test_connection()

        self.assertIn('API Key', str(caught.exception))

    def test_17_the_test_posts_an_empty_batch_with_the_key(self):
        """An empty batch is what makes the test harmless: it writes nothing."""
        connection = self._connection()

        with patch(POST, return_value=FakeResponse(200, {'status': 'success'})) as post:
            with self.assertRaises(UserError):
                connection.action_test_connection()

        _args, kwargs = post.call_args
        self.assertEqual(kwargs['json']['records'], [])
        self.assertEqual(kwargs['json']['slave_token'], connection.slave_token)
        self.assertEqual(kwargs['headers']['Authorization'],
                         'Bearer %s' % connection.api_key)
