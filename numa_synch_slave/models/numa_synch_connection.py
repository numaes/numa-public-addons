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
    
    sync_interval_number = fields.Integer(
        string='Sync Interval',
        default=15,
        required=True,
        help='Number of intervals between synchronizations'
    )
    
    sync_interval_type = fields.Selection(
        [
            ('minutes', 'Minutes'),
            ('hours', 'Hours'),
            ('days', 'Days'),
        ],
        string='Interval Type',
        default='minutes',
        required=True,
        help='Time unit for the synchronization interval'
    )
    
    use_scheduled_time = fields.Boolean(
        string='Use Scheduled Time',
        default=False,
        help='If enabled, synchronization will run at a specific time of day'
    )
    
    sync_schedule_time = fields.Float(
        string='Scheduled Time',
        help='Time of day to run synchronization (24-hour format, e.g., 14.5 = 14:30)'
    )
    
    cron_id = fields.Many2one(
        'ir.cron',
        string='Cron Job',
        readonly=True,
        copy=False,
        help='Automatically created cron job for this connection'
    )

    @api.model
    def create(self, vals):
        """Ensure slave_token is generated if not provided and create cron job"""
        if 'slave_token' not in vals or not vals.get('slave_token'):
            vals['slave_token'] = str(uuid.uuid4())
        record = super().create(vals)
        record._create_or_update_cron()
        return record
    
    def write(self, vals):
        """Update cron job when sync settings change"""
        result = super().write(vals)
        # Update cron if sync-related fields changed
        sync_fields = {'active', 'sync_interval_number', 'sync_interval_type', 
                      'use_scheduled_time', 'sync_schedule_time'}
        if sync_fields.intersection(set(vals.keys())):
            for record in self:
                record._create_or_update_cron()
        return result
    
    def unlink(self):
        """Delete associated cron jobs when connection is deleted"""
        for record in self:
            if record.cron_id:
                record.cron_id.unlink()
        return super().unlink()

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
    
    @api.constrains('sync_interval_number')
    def _check_sync_interval_number(self):
        """Validate sync interval is positive"""
        for record in self:
            if record.sync_interval_number <= 0:
                raise ValidationError(_(
                    'Sync interval must be greater than 0'
                ))
    
    @api.constrains('sync_schedule_time')
    def _check_sync_schedule_time(self):
        """Validate scheduled time is in valid range"""
        for record in self:
            if record.use_scheduled_time and record.sync_schedule_time is not False:
                if record.sync_schedule_time < 0 or record.sync_schedule_time >= 24:
                    raise ValidationError(_(
                        'Scheduled time must be between 0.0 and 23.99 (24-hour format)'
                    ))
    
    def _create_or_update_cron(self):
        """
        Create or update the cron job for this connection.
        
        This method is called automatically when sync settings change.
        """
        self.ensure_one()
        
        cron_model = self.env['ir.cron']
        
        # Prepare cron name
        cron_name = f'Sync: {self.name}'
        
        # Prepare code to call
        # In Odoo cron with state='code', 'env' is the environment
        # We need to browse the specific connection and call its method
        cron_code = f'env["numa.synch.connection"].browse({self.id}).action_run_sync()'
        
        # Calculate nextcall based on scheduled time if enabled
        nextcall = False
        if self.use_scheduled_time and self.sync_schedule_time is not False:
            from datetime import datetime, time
            from odoo import fields as odoo_fields
            
            # Get current date/time
            now = datetime.now()
            
            # Convert float time to time object
            hours = int(self.sync_schedule_time)
            minutes = int((self.sync_schedule_time - hours) * 60)
            scheduled_time = time(hours, minutes)
            
            # Create datetime for today at scheduled time
            nextcall_dt = datetime.combine(now.date(), scheduled_time)
            
            # If scheduled time has passed today, schedule for tomorrow
            if nextcall_dt <= now:
                from datetime import timedelta
                nextcall_dt += timedelta(days=1)
            
            # Convert to Odoo datetime string
            nextcall = odoo_fields.Datetime.to_string(nextcall_dt)
        
        if self.cron_id:
            # Update existing cron
            self.cron_id.write({
                'name': cron_name,
                'active': self.active,
                'interval_number': self.sync_interval_number,
                'interval_type': self.sync_interval_type,
                'code': cron_code,
                'nextcall': nextcall or self.cron_id.nextcall,
            })
        else:
            # Create new cron
            cron_vals = {
                'name': cron_name,
                'model_id': self.env['ir.model']._get_id('numa.synch.connection'),
                'state': 'code',
                'code': cron_code,
                'interval_number': self.sync_interval_number,
                'interval_type': self.sync_interval_type,
                'numbercall': -1,  # Unlimited
                'active': self.active,
                'doall': False,
            }
            
            if nextcall:
                cron_vals['nextcall'] = nextcall
            
            cron = cron_model.create(cron_vals)
            self.cron_id = cron.id

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
