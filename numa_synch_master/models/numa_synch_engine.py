"""
Master Synchronization Engine Implementation

Implements the Master-side logic for processing incoming synchronization batches
using the Two-Phase Write strategy to handle circular dependencies.
"""

from odoo import models, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.fields import Datetime
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class NumaSynchEngineMaster(models.Model):
    """
    Master Synchronization Engine
    
    Inherits from the abstract numa.synch.engine and implements
    Master-specific logic for processing incoming batches.
    """
    _name = 'numa.synch.engine'
    _inherit = 'numa.synch.engine'
    _description = 'Master Synchronization Engine'

    def process_incoming_batch_master(self, slave_token, records):
        """
        Process an incoming synchronization batch from a Slave.
        
        This method implements the Two-Phase Write strategy:
        - Phase 1: Create skeleton records (scalar fields only)
        - Phase 2: Decorate with relations (Many2one, x2many)
        
        :param str slave_token: Identifier of the Slave node (UUID)
        :param list records: List of record dictionaries with format:
            [
                {
                    "model": "res.partner",
                    "local_id": 123,  # Slave's local ID
                    "vals": {...},    # Field values
                    "write_date": "2024-01-01T12:00:00"  # Optional timestamp
                },
                ...
            ]
        :return: Dictionary with updated mappings:
            {
                "updated_mappings": [
                    {
                        "model": "res.partner",
                        "slave_id": 123,
                        "master_id": 456
                    },
                    ...
                ]
            }
        :rtype: dict
        """
        if not slave_token:
            raise ValidationError(_('slave_token is required'))
        
        if not records or not isinstance(records, list):
            raise ValidationError(_('records must be a non-empty list'))
        
        # Wrap everything in sync context to disable automations
        with self.env.context(sync_mode=True, tracking_disable=True):
            updated_mappings = []
            
            # Namespace Safety: Get allowed models from sync rules
            allowed_models = self._get_allowed_models()
            
            # Phase 1: Create skeleton records (scalar fields only)
            phase1_results = {}
            for record_data in records:
                model_name = record_data.get('model')
                slave_local_id = record_data.get('local_id')
                vals = record_data.get('vals', {})
                incoming_write_date = record_data.get('write_date')
                
                if not model_name or slave_local_id is None:
                    _logger.warning(
                        'Skipping record with missing model or local_id: %s',
                        record_data
                    )
                    continue
                
                # Namespace Safety: Check if model is allowed
                if model_name not in allowed_models:
                    _logger.warning(
                        'Model %s is not allowed for synchronization (not in sync rules)',
                        model_name
                    )
                    continue
                
                try:
                    result = self._process_record_phase1(
                        model_name,
                        slave_local_id,
                        vals,
                        slave_token,
                        incoming_write_date
                    )
                    if result:
                        phase1_results[(model_name, slave_local_id)] = result
                        updated_mappings.append({
                            'model': model_name,
                            'slave_id': slave_local_id,
                            'master_id': result['master_id']
                        })
                except Exception as e:
                    _logger.error(
                        'Error processing record Phase 1: %s (model: %s, slave_id: %s): %s',
                        model_name, slave_local_id, str(e),
                        exc_info=True
                    )
                    # Continue with other records
                    continue
            
            # Phase 2: Decorate with relations
            for record_data in records:
                model_name = record_data.get('model')
                slave_local_id = record_data.get('local_id')
                vals = record_data.get('vals', {})
                
                if not model_name or slave_local_id is None:
                    continue
                
                # Skip if Phase 1 failed
                phase1_key = (model_name, slave_local_id)
                if phase1_key not in phase1_results:
                    continue
                
                master_id = phase1_results[phase1_key]['master_id']
                
                try:
                    self._process_record_phase2(
                        model_name,
                        master_id,
                        vals,
                        slave_token
                    )
                except Exception as e:
                    _logger.error(
                        'Error processing record Phase 2: %s (model: %s, master_id: %s): %s',
                        model_name, master_id, str(e),
                        exc_info=True
                    )
                    # Continue with other records
                    continue
            
            return {
                'updated_mappings': updated_mappings
            }

    def _get_allowed_models(self):
        """
        Get the set of model names that are allowed for synchronization.
        
        :return: Set of model names
        :rtype: set
        """
        rules = self.env['numa.synch.rule'].search([
            ('active', '=', True),
            ('direction', 'in', ['bidirectional', 'incoming'])
        ])
        
        allowed_models = set()
        for rule in rules:
            if rule.model_name:
                allowed_models.add(rule.model_name)
        
        return allowed_models

    def _process_record_phase1(self, model_name, slave_local_id, vals, slave_token, incoming_write_date=None):
        """
        Phase 1: Create or identify skeleton record (scalar fields only).
        
        :param str model_name: Technical name of the model
        :param int slave_local_id: Local ID in the Slave database
        :param dict vals: Field values dictionary
        :param str slave_token: Slave node identifier
        :param str incoming_write_date: Optional write_date from Slave
        :return: Dictionary with master_id, or None if skipped
        :rtype: dict or None
        """
        # Check if mapping already exists
        # From Master's perspective: slave_local_id is the "remote_id"
        synch_map = self.env['numa.synch.map']
        existing_master_id = synch_map.get_local_id(
            model_name,
            slave_local_id,  # This is the remote_id from Master's perspective
            slave_token
        )
        
        # Get the model - validate it exists
        try:
            model = self.env[model_name]
            if not model:
                _logger.error('Model %s does not exist', model_name)
                return None
        except KeyError:
            _logger.error('Model %s does not exist', model_name)
            return None
        
        # Parse incoming write_date
        incoming_timestamp = None
        if incoming_write_date:
            try:
                if isinstance(incoming_write_date, str):
                    incoming_timestamp = Datetime.from_string(incoming_write_date)
                elif isinstance(incoming_write_date, datetime):
                    incoming_timestamp = incoming_write_date
            except Exception as e:
                _logger.warning(
                    'Could not parse incoming write_date: %s',
                    str(e)
                )
        
        if existing_master_id:
            # Record exists - apply conflict resolution
            master_record = model.browse(existing_master_id)
            if not master_record.exists():
                # Mapping exists but record was deleted - create new
                existing_master_id = None
            else:
                # Apply Last Write Wins logic
                applied = self._apply_conflict_logic(
                    master_record,
                    vals,
                    incoming_timestamp,
                    slave_token
                )
                if not applied:
                    # Changes were ignored due to conflict
                    return {
                        'master_id': existing_master_id,
                        'action': 'ignored'
                    }
        
        if not existing_master_id:
            # New record - create skeleton (scalar fields only)
            scalar_vals = self._extract_scalar_fields(model_name, vals)
            
            try:
                master_record = model.create(scalar_vals)
                master_id = master_record.id
                
                # Create mapping
                synch_map.set_mapping(
                    model_name,
                    master_id,  # In Master, master_id is the "local_id"
                    slave_local_id,  # In Master, slave_id is the "remote_id"
                    slave_token
                )
                
                return {
                    'master_id': master_id,
                    'action': 'created'
                }
            except Exception as e:
                _logger.error(
                    'Error creating record in Phase 1: %s (model: %s): %s',
                    model_name, str(e),
                    exc_info=True
                )
                raise
        
        return {
            'master_id': existing_master_id,
            'action': 'updated'
        }

    def _process_record_phase2(self, model_name, master_id, vals, slave_token):
        """
        Phase 2: Decorate record with relational fields.
        
        :param str model_name: Technical name of the model
        :param int master_id: Master record ID
        :param dict vals: Field values dictionary
        :param str slave_token: Slave node identifier
        """
        model = self.env[model_name]
        master_record = model.browse(master_id)
        
        if not master_record.exists():
            _logger.warning(
                'Master record does not exist: %s (ID: %s)',
                model_name, master_id
            )
            return
        
        # Extract relational fields
        relational_vals = self._extract_relational_fields(model_name, vals, slave_token)
        
        if not relational_vals:
            # No relational fields to update
            return
        
        try:
            master_record.write(relational_vals)
        except Exception as e:
            _logger.error(
                'Error updating relational fields in Phase 2: %s (model: %s, ID: %s): %s',
                model_name, master_id, str(e),
                exc_info=True
            )
            raise

    def _extract_scalar_fields(self, model_name, vals):
        """
        Extract only scalar fields from vals (Char, Integer, Float, Boolean, Date, Datetime, Text, Selection).
        Exclude Many2one, One2many, Many2many, and Binary fields.
        
        :param str model_name: Technical name of the model
        :param dict vals: Full field values dictionary
        :return: Dictionary with only scalar fields
        :rtype: dict
        """
        model = self.env[model_name]
        model_fields = model._fields
        
        scalar_vals = {}
        
        for field_name, field_value in vals.items():
            if field_name not in model_fields:
                continue
            
            field = model_fields[field_name]
            
            # Skip relational fields (will be handled in Phase 2)
            if field.type in ('many2one', 'one2many', 'many2many'):
                continue
            
            # Skip binary fields (performance)
            if field.type == 'binary':
                continue
            
            # Skip computed fields that are not stored
            if field.compute and not field.store:
                continue
            
            # Skip related fields
            if field.related:
                continue
            
            # Handle date/datetime strings
            if field.type in ('date', 'datetime') and isinstance(field_value, str):
                try:
                    if field.type == 'date':
                        scalar_vals[field_name] = field_value  # Will be converted by Odoo
                    else:
                        scalar_vals[field_name] = field_value  # Will be converted by Odoo
                except Exception:
                    _logger.warning(
                        'Could not parse %s field %s.%s: %s',
                        field.type, model_name, field_name, field_value
                    )
                    continue
            
            # Include scalar field
            scalar_vals[field_name] = field_value
        
        return scalar_vals

    def _extract_relational_fields(self, model_name, vals, slave_token):
        """
        Extract and translate relational fields (Many2one, One2many, Many2many).
        Translate Slave IDs to Master IDs using the mapping table.
        
        :param str model_name: Technical name of the model
        :param dict vals: Full field values dictionary
        :param str slave_token: Slave node identifier
        :return: Dictionary with translated relational fields
        :rtype: dict
        """
        model = self.env[model_name]
        model_fields = model._fields
        
        relational_vals = {}
        
        for field_name, field_value in vals.items():
            if field_name not in model_fields:
                continue
            
            field = model_fields[field_name]
            
            # Handle Many2one fields
            if field.type == 'many2one':
                if not field_value:
                    relational_vals[field_name] = False
                elif isinstance(field_value, dict) and field_value.get('__type__') == 'ref':
                    # Translate reference
                    master_id = self._parse_incoming_ref(field_value, slave_token)
                    if master_id:
                        relational_vals[field_name] = master_id
                    else:
                        _logger.warning(
                            'Could not resolve Many2one reference for %s.%s: %s',
                            model_name, field_name, field_value
                        )
                        # Skip this field (Reference Safety)
                elif isinstance(field_value, int):
                    # Direct ID - try to translate
                    ref_dict = {
                        '__type__': 'ref',
                        'model': field.comodel_name,
                        'id': field_value
                    }
                    master_id = self._parse_incoming_ref(ref_dict, slave_token)
                    if master_id:
                        relational_vals[field_name] = master_id
                    else:
                        _logger.warning(
                            'Could not resolve Many2one ID for %s.%s: %s',
                            model_name, field_name, field_value
                        )
            
            # Handle One2many fields
            elif field.type == 'one2many':
                if not field_value:
                    relational_vals[field_name] = [(5, 0, 0)]  # Clear all
                elif isinstance(field_value, list):
                    # For One2many, we need to handle commands
                    # For now, we'll translate IDs in link commands
                    translated_commands = []
                    for cmd in field_value:
                        if isinstance(cmd, (list, tuple)) and len(cmd) >= 2:
                            cmd_type = cmd[0]
                            if cmd_type in (6, 4):  # (6, 0, [ids]) or (4, id)
                                # Link command - translate IDs
                                if cmd_type == 6:
                                    ids = cmd[2] if len(cmd) > 2 else []
                                    translated_ids = []
                                    for slave_id in ids:
                                        ref_dict = {
                                            '__type__': 'ref',
                                            'model': field.comodel_name,
                                            'id': slave_id
                                        }
                                        master_id = self._parse_incoming_ref(ref_dict, slave_token)
                                        if master_id:
                                            translated_ids.append(master_id)
                                    if translated_ids:
                                        translated_commands.append((6, 0, translated_ids))
                                elif cmd_type == 4:
                                    slave_id = cmd[1]
                                    ref_dict = {
                                        '__type__': 'ref',
                                        'model': field.comodel_name,
                                        'id': slave_id
                                    }
                                    master_id = self._parse_incoming_ref(ref_dict, slave_token)
                                    if master_id:
                                        translated_commands.append((4, master_id))
                            else:
                                # Other commands (create, update, delete) - pass through
                                translated_commands.append(cmd)
                        else:
                            translated_commands.append(cmd)
                    if translated_commands:
                        relational_vals[field_name] = translated_commands
            
            # Handle Many2many fields
            elif field.type == 'many2many':
                if not field_value:
                    relational_vals[field_name] = [(5, 0, 0)]  # Clear all
                elif isinstance(field_value, list):
                    # Translate list of references or IDs
                    translated_ids = []
                    for item in field_value:
                        if isinstance(item, dict) and item.get('__type__') == 'ref':
                            master_id = self._parse_incoming_ref(item, slave_token)
                            if master_id:
                                translated_ids.append(master_id)
                        elif isinstance(item, int):
                            ref_dict = {
                                '__type__': 'ref',
                                'model': field.comodel_name,
                                'id': item
                            }
                            master_id = self._parse_incoming_ref(ref_dict, slave_token)
                            if master_id:
                                translated_ids.append(master_id)
                    if translated_ids:
                        relational_vals[field_name] = [(6, 0, translated_ids)]
        
        return relational_vals

    def _apply_conflict_logic(self, record, vals, incoming_timestamp, slave_token):
        """
        Apply Last Write Wins (LWW) conflict resolution logic.
        
        :param recordset record: Master record
        :param dict vals: Incoming field values from Slave
        :param datetime incoming_timestamp: Write date from Slave
        :param str slave_token: Slave node identifier
        :return: True if changes were applied, False if ignored
        :rtype: bool
        """
        if not incoming_timestamp:
            # No timestamp provided - apply changes
            scalar_vals = self._extract_scalar_fields(record._name, vals)
            if scalar_vals:
                record.write(scalar_vals)
            return True
        
        # Compare timestamps
        master_write_date = record.write_date
        
        if not master_write_date:
            # Master has no write_date - apply changes
            scalar_vals = self._extract_scalar_fields(record._name, vals)
            if scalar_vals:
                record.write(scalar_vals)
            return True
        
        # Convert to datetime for comparison
        if isinstance(master_write_date, str):
            master_write_date = Datetime.from_string(master_write_date)
        
        if incoming_timestamp > master_write_date:
            # Slave is newer - apply changes
            scalar_vals = self._extract_scalar_fields(record._name, vals)
            if scalar_vals:
                record.write(scalar_vals)
                # Log that we overwrote Master's data
                record.message_post(
                    body=_(
                        'Synchronization: Updated from Slave (%s) - '
                        'Slave timestamp (%s) is newer than Master (%s)'
                    ) % (
                        slave_token,
                        incoming_timestamp,
                        master_write_date
                    )
                )
            return True
        else:
            # Master is newer or equal - ignore Slave changes
            # Log the conflict
            record.message_post(
                body=_(
                    'Synchronization: Ignored update from Slave (%s) - '
                    'Master timestamp (%s) is newer or equal to Slave (%s)'
                ) % (
                    slave_token,
                    master_write_date,
                    incoming_timestamp
                )
            )
            return False
