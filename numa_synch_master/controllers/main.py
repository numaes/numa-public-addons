"""HTTP endpoint through which a Slave hands its batches to the Master."""

import logging

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class NumaSynchMasterController(http.Controller):
    """The Master's synchronization API."""

    # [20.0] Three things changed here, and together they are the difference
    # between an endpoint that answers and one that never did.
    #
    # `type='json2'` instead of `type='json'`. The latter is a JSON-RPC route: it
    # reads the payload out of a `{"jsonrpc": "2.0", "params": {...}}` envelope and
    # answers inside a `{"result": ...}` one. The Slave has always posted a flat
    # body and always read a flat answer, so the two sides never spoke the same
    # protocol. `json2` is the flat one, which is what the Slave already speaks.
    #
    # `auth='bearer'` instead of `auth='user'`. The Slave sends
    # `Authorization: Bearer <api_key>` and nothing else -- no session, no cookie --
    # so `auth='user'` could only ever answer "session expired". Odoo 20 checks that
    # header against `res.users.apikeys`, which is exactly the handshake the Slave
    # was written for. `bearer_scope='rpc'` is the global-key scope core uses.
    #
    # And the body no longer reads `request.jsonrequest`, which has not existed on
    # `request` since 17.0. It raised `AttributeError` on the endpoint's first line,
    # the blanket `except Exception` below turned it into an "Internal server error"
    # answer, and that answer went back with HTTP 200 -- so the Slave logged an
    # unknown error and `test_connection` reported success.
    @http.route(
        '/numa_synch/api/v1/sync_batch',
        type='json2',
        auth='bearer',
        bearer_scope='rpc',
        methods=['POST'],
        csrf=False,
    )
    def sync_batch(self, slave_token=None, records=None, meta=None, **kwargs):
        """Receive a synchronization batch from a Slave and process it.

        Body::

            {
              "slave_token": "uuid-string",
              "records": [{"model": ..., "local_id": ..., "vals": {...},
                           "write_date": "2024-01-01T12:00:00"}, ...],
              "meta": {...}          # optional, first batch only
            }

        Answer::

            {
              "status": "success" | "error",
              "message": "...",
              "updated_mappings": [{"model": ..., "slave_id": ..., "master_id": ...}]
            }

        The answer is always this shape, including for a refusal: a Slave that cannot
        parse the reply cannot record what the Master did accept, and would send the
        same batch again.
        """
        if not slave_token:
            return self._error('slave_token is required')

        if records is None:
            records = []

        if not isinstance(records, list):
            return self._error('records must be a list')

        if not records:
            # An empty batch is how the Slave tests the connection: it proves the URL
            # resolves and the API key is accepted, without writing anything.
            return {
                'status': 'success',
                'message': 'No records to process',
                'updated_mappings': [],
            }

        try:
            result = request.env['numa.synch.engine'].process_incoming_batch_master(
                slave_token, records, meta)
        except ValidationError as error:
            _logger.warning('Rejected a batch from slave %s: %s', slave_token, error)
            return self._error('Validation error: %s' % error)
        except AccessError as error:
            _logger.warning('Denied a batch from slave %s: %s', slave_token, error)
            return self._error('Access denied: %s' % error)
        except Exception as error:  # noqa: BLE001 -- see the docstring above
            _logger.exception('Could not process a batch from slave %s.', slave_token)
            return self._error('Internal server error: %s' % error)

        return {
            'status': 'success',
            'message': 'Processed %s records' % len(records),
            'updated_mappings': result.get('updated_mappings', []),
        }

    def _error(self, message):
        return {'status': 'error', 'message': message, 'updated_mappings': []}
