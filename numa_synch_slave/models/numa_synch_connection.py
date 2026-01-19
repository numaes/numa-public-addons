"""
Synchronization Connection Configuration

Stores credentials and settings to connect to the Master server.
"""

import uuid
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import requests

_logger = logging.getLogger(__name__)


class NumaSynchConnection(models.Model):
    """
    Synchronization Connection Configuration
    
    Stores the connection details to the Master server and manages
    the synchronization process.
    """
    _name = 'numa.synch.connection'
    _description = 'Synchronization Connection to Master'
    _rec_name = 'name'

    name = fields.Char(
        string='Name',
        required=True,
        help='Descriptive name for this connection (e.g., "Central Server")'
    )
    
    master_url = fields.Char(
        string='Master URL',
        required=True,
        help='Base URL of the Master server (e.g., https://my-central-odoo.com)'
    )
    
    master_db = fields.Char(
        string='Master Database',
        required=True,
        help='Database name on the Master server'
    )
    
    api_key = fields.Char(
        string='API Key',
        required=True,
        help='User API Key generated on the Master server for authentication'
    )
    
    slave_token = fields.Char(
        string='Slave Token',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: str(uuid.uuid4()),
        help='Unique identifier for this Slave node (UUID). '
             'Generated automatically and cannot be changed.'
    )
    
    last_sync_date = fields.Datetime(
        string='Last Sync Date',
        readonly=True,
        help='Timestamp of the last successful synchronization'
    )
    
    batch_size = fields.Integer(
        string='Batch Size',
        default=100,
        required=True,
        help='Number of records to send per batch request'
    )
    
    active = fields.Boolean(
        string='Active',
        default=True,
        help='If unchecked, synchronization will be disabled'
    )

    @api.model
    def create(self, vals):
        """Ensure slave_token is generated if not provided"""
        if 'slave_token' not in vals or not vals.get('slave_token'):
            vals['slave_token'] = str(uuid.uuid4())
        return super().create(vals)

    @api.constrains('master_url')
    def _check_master_url(self):
        """Validate master URL format"""
        for record in self:
            if record.master_url:
                url = record.master_url.strip()
                if not url.startswith(('http://', 'https://')):
                    raise ValidationError(_(
                        'Master URL must start with http:// or https://'
                    ))

    @api.constrains('batch_size')
    def _check_batch_size(self):
        """Validate batch size is positive"""
        for record in self:
            if record.batch_size <= 0:
                raise ValidationError(_(
                    'Batch size must be greater than 0'
                ))

    def action_test_connection(self):
        """
        Test the connection to the Master server.
        
        :return: UserError with success message or exception on failure
        """
        self.ensure_one()
        
        if not self.master_url or not self.api_key:
            raise UserError(_(
                'Master URL and API Key are required to test connection'
            ))
        
        # Clean URL (remove trailing slash)
        master_url = self.master_url.rstrip('/')
        endpoint = f"{master_url}/numa_synch/api/v1/sync_batch"
        
        try:
            # Send a minimal test request
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            
            # Send empty batch as test
            payload = {
                'slave_token': self.slave_token,
                'records': []
            }
            
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                raise UserError(_(
                    'Connection test successful! Master server is reachable.'
                ))
            elif response.status_code == 401:
                raise UserError(_(
                    'Authentication failed. Please check your API Key.'
                ))
            elif response.status_code == 403:
                raise UserError(_(
                    'Access denied. Please check your API Key permissions.'
                ))
            else:
                raise UserError(_(
                    'Connection test failed with status code %s: %s'
                ) % (response.status_code, response.text[:200]))
                
        except requests.exceptions.ConnectionError:
            raise UserError(_(
                'Could not connect to Master server. Please check the URL and network connectivity.'
            ))
        except requests.exceptions.Timeout:
            raise UserError(_(
                'Connection timeout. The Master server did not respond in time.'
            ))
        except requests.exceptions.RequestException as e:
            raise UserError(_(
                'Connection error: %s'
            ) % str(e))
        except Exception as e:
            _logger.exception('Unexpected error testing connection')
            raise UserError(_(
                'Unexpected error: %s'
            ) % str(e))

    def action_run_sync(self):
        """
        Manually trigger a synchronization cycle.
        
        This method is called by the cron job or can be triggered manually.
        """
        self.ensure_one()
        
        if not self.active:
            raise UserError(_(
                'Cannot run synchronization: connection is not active'
            ))
        
        if not self.master_url or not self.api_key or not self.slave_token:
            raise UserError(_(
                'Connection configuration is incomplete. '
                'Please check Master URL, API Key, and Slave Token.'
            ))
        
        # Get the synchronization engine
        engine = self.env['numa.synch.engine']
        
        # Run the synchronization cycle
        try:
            engine.run_synchronization_cycle(self)
        except Exception as e:
            _logger.exception('Error running synchronization cycle')
            raise UserError(_(
                'Synchronization failed: %s'
            ) % str(e))

    @api.model
    def _cron_sync_all_connections(self):
        """
        Cron method to synchronize all active connections.
        
        This method is called by the scheduled action.
        """
        connections = self.search([('active', '=', True)])
        
        for connection in connections:
            try:
                connection.action_run_sync()
            except Exception as e:
                _logger.error(
                    'Error syncing connection %s (ID: %s): %s',
                    connection.name, connection.id, str(e),
                    exc_info=True
                )
                # Continue with other connections
                continue
