"""
HTTP Controller for Master Synchronization API

Exposes JSON-RPC endpoint for Slaves to send synchronization batches.
"""

import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError, AccessError

_logger = logging.getLogger(__name__)


class NumaSynchMasterController(http.Controller):
    """
    Controller for Master synchronization API endpoints
    """

    @http.route(
        '/numa_synch/api/v1/sync_batch',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=False
    )
    def sync_batch(self, **kwargs):
        """
        Receive and process a synchronization batch from a Slave.
        
        Expected JSON payload:
        {
            "slave_token": "uuid-string",
            "records": [
                {
                    "model": "res.partner",
                    "local_id": 123,
                    "vals": {...},
                    "write_date": "2024-01-01T12:00:00"
                },
                ...
            ]
        }
        
        Returns:
        {
            "status": "success" | "error",
            "message": "...",
            "updated_mappings": [
                {
                    "model": "res.partner",
                    "slave_id": 123,
                    "master_id": 456
                },
                ...
            ]
        }
        """
        try:
            # Get JSON payload
            json_data = request.jsonrequest
            
            if not json_data:
                return {
                    'status': 'error',
                    'message': 'No JSON payload provided',
                    'updated_mappings': []
                }
            
            slave_token = json_data.get('slave_token')
            records = json_data.get('records', [])
            
            # Validate required fields
            if not slave_token:
                return {
                    'status': 'error',
                    'message': 'slave_token is required',
                    'updated_mappings': []
                }
            
            if not isinstance(records, list):
                return {
                    'status': 'error',
                    'message': 'records must be a list',
                    'updated_mappings': []
                }
            
            if not records:
                return {
                    'status': 'success',
                    'message': 'No records to process',
                    'updated_mappings': []
                }
            
            # Get the synchronization engine
            engine = request.env['numa.synch.engine']
            
            # Process the batch
            result = engine.process_incoming_batch_master(slave_token, records)
            
            return {
                'status': 'success',
                'message': f'Processed {len(records)} records',
                'updated_mappings': result.get('updated_mappings', [])
            }
            
        except ValidationError as e:
            _logger.error('Validation error in sync_batch: %s', str(e))
            return {
                'status': 'error',
                'message': f'Validation error: {str(e)}',
                'updated_mappings': []
            }
        except AccessError as e:
            _logger.error('Access error in sync_batch: %s', str(e))
            return {
                'status': 'error',
                'message': f'Access denied: {str(e)}',
                'updated_mappings': []
            }
        except Exception as e:
            _logger.exception('Unexpected error in sync_batch: %s', str(e))
            return {
                'status': 'error',
                'message': f'Internal server error: {str(e)}',
                'updated_mappings': []
            }
