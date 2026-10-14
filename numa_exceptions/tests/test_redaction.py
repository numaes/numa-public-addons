# -*- coding: utf-8 -*-
"""A credential in the parameters of a failing call is never stored nor logged."""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from ..models import exceptions as capture

SECRET = '0f1e2d3c4b5a69788796a5b4c3d2e1f0aabbccdd'
# What an external JSON-RPC client sent in production: args as an object keyed
# by position, the password at "2" (and the uid missing).
JSONRPC_PARAMS = {'service': 'object', 'method': 'execute_kw', 'args': {
    '0': 'prod-db', '2': SECRET, '3': 'crm.lead', '4': 'create', '5': [{'name': 'Lead'}]}}


@tagged('post_install', '-at_install')
class TestRedaction(TransactionCase):

    def test_secrets_are_collected_by_name_and_position(self):
        self.assertEqual(capture.collect_secrets(JSONRPC_PARAMS), {SECRET})
        self.assertEqual(capture.collect_secrets({'service': 'object', 'args': ['db', 2, SECRET, 'res.partner']}),
                         {SECRET})
        self.assertEqual(capture.collect_secrets({'service': 'db', 'args': ['master-pass-123', 'db']}),
                         {'master-pass-123'})
        self.assertEqual(capture.collect_secrets({'login': 'admin', 'password': 'p4ssw0rd!'}), {'p4ssw0rd!'})

    def test_a_jsonrpc_password_never_reaches_the_record_nor_the_log(self):
        """It was stored in the record, its frames' locals and the server log."""
        created = []
        Exception_ = type(self.env['base.general_exception'])
        original_create = Exception_.create

        def capture_create(self_, vals_list):
            created.append(vals_list)
            return original_create(self_, vals_list)

        params = JSONRPC_PARAMS
        try:
            args = params['args']
            db, uid, passwd = args[0], int(args[1]), args[2]  # KeyError: 0, as in production
        except Exception as e:  # noqa: BLE001
            # The registry cursor of register_exception is this test's cursor:
            # its commit must not end the test transaction.
            with patch.object(Exception_, 'create', capture_create), \
                    patch.object(type(self.env.cr), 'commit', lambda cr: None), \
                    self.assertLogs('odoo.addons.numa_exceptions', level='ERROR') as logs:
                capture.register_exception('jsonrpc', 'dispatch', {'params': params}, self.env.cr.dbname, 1, e)
        self.assertTrue(created)
        self.assertNotIn(SECRET, repr(created))
        self.assertNotIn(SECRET, '\n'.join(logs.output))
        self.assertIn('crm.lead', '\n'.join(logs.output), "the rest of the call is kept for diagnosis")
