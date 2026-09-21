"""Shared setup for the Slave's tests."""

import json

from odoo.tests import TransactionCase


class FakeResponse:
    """What `requests.post` gives back, reduced to what the Slave reads."""

    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body or {})

    def json(self):
        if self._body is None:
            raise ValueError('no JSON object could be decoded')
        return self._body


class SlaveSynchCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env['numa.synch.engine']
        cls.Connection = cls.env['numa.synch.connection']

    def _connection(self, **overrides):
        vals = {
            'name': 'Central',
            'master_url': 'https://master.example.com',
            'master_db': 'master_db',
            'api_key': 'a-key',
        }
        vals.update(overrides)
        return self.Connection.create(vals)

    @classmethod
    def _rule(cls, model_name, **overrides):
        model_id = cls.env['ir.model']._get_id(model_name)
        assert model_id, '%s is not a model in this database.' % model_name
        vals = {
            'name': 'Sync %s' % model_name,
            'model_id': model_id,
            'direction': 'bidirectional',
        }
        vals.update(overrides)
        return cls.env['numa.synch.rule'].create(vals)
