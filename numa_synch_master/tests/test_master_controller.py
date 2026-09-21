"""The wire: how a Slave's HTTP request reaches the engine.

The endpoint had never answered a Slave. Three things had to line up for that, and
each of them is asserted here on its own, because each failed silently: the route's
protocol, the route's authentication, and the shape of the body that comes back.
"""

import json

from odoo.addons.numa_synch_master.controllers.main import NumaSynchMasterController
from odoo.tests import HttpCase, tagged

from .common import MasterSynchCase

ENDPOINT = '/numa_synch/api/v1/sync_batch'


@tagged('post_install', '-at_install')
class TestMasterRouting(MasterSynchCase):
    """What the route declares. No HTTP needed to check it."""

    def _routing(self):
        routing = NumaSynchMasterController.sync_batch.original_routing
        self.assertIn(ENDPOINT, routing['routes'])
        return routing

    def test_01_the_route_is_flat_json_not_json_rpc(self):
        """`json2` in, `json2` out.

        The route used to be `type='json'`, which is JSON-RPC: it reads the payload
        from a `params` envelope and answers inside a `result` one. The Slave has
        always posted a flat body and always read a flat answer, so the two halves
        of this pair never spoke the same protocol -- every batch came back as an
        unparseable envelope and was logged as an unknown error.
        """
        self.assertEqual(self._routing()['type'], 'json2')

    def test_02_the_route_authenticates_by_bearer_token(self):
        """The Slave sends an API key and nothing else.

        `auth='user'` wants a session cookie, which a server-to-server client does
        not have, so the endpoint could only ever answer "session expired" -- while
        the `Authorization: Bearer` header the Slave does send went unread.
        """
        routing = self._routing()
        self.assertEqual(routing['auth'], 'bearer')
        self.assertEqual(routing['bearer_scope'], 'rpc')


@tagged('post_install', '-at_install')
class TestMasterEndpoint(HttpCase, MasterSynchCase):
    """What the endpoint answers, over real HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_key = cls.env['res.users.apikeys'].with_user(
            cls.env.ref('base.user_admin'))._generate('rpc', 'synch slave', False)

    def _post(self, payload, key=None):
        response = self.url_open(
            ENDPOINT,
            data=json.dumps(payload),
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer %s' % (self.api_key if key is None else key),
            },
            timeout=30,
        )
        return response

    def test_03_a_batch_posted_flat_is_written(self):
        """The end-to-end proof: an ordinary Slave request creates a record."""
        response = self._post({
            'slave_token': self.SLAVE,
            'records': [self._record('res.partner', 201, {'name': 'Over The Wire'})],
        })

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(len(body['updated_mappings']), 1)

        master_id = body['updated_mappings'][0]['master_id']
        self.assertEqual(
            self.env['res.partner'].browse(master_id).name, 'Over The Wire')

    def test_04_an_empty_batch_is_the_connection_test(self):
        """This is what `Test Connection` on the Slave sends: it must succeed.

        And it must say so in the body, not only in the status code -- the Slave
        used to read the code alone and reported success on every refusal.
        """
        response = self._post({'slave_token': self.SLAVE, 'records': []})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')

    def test_05_a_missing_token_is_refused_in_the_body(self):
        body = self._post({'records': []}).json()

        self.assertEqual(body['status'], 'error')
        self.assertIn('slave_token', body['message'])
        self.assertEqual(body['updated_mappings'], [])

    def test_06_records_must_be_a_list(self):
        body = self._post({'slave_token': self.SLAVE, 'records': 'nope'}).json()

        self.assertEqual(body['status'], 'error')
        self.assertEqual(body['updated_mappings'], [])

    def test_07_a_wrong_api_key_is_rejected(self):
        """Without this the endpoint is an unauthenticated write into the database."""
        response = self._post(
            {'slave_token': self.SLAVE, 'records': []}, key='not-a-real-key')

        self.assertEqual(response.status_code, 401)

    def test_08_no_api_key_is_rejected(self):
        response = self.url_open(
            ENDPOINT,
            data=json.dumps({'slave_token': self.SLAVE, 'records': []}),
            headers={'Content-Type': 'application/json'},
            timeout=30,
        )

        self.assertEqual(response.status_code, 401)
