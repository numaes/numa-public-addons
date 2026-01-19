"""
Abstract Synchronization Engine

This model defines the serialization protocol for synchronization.
It is an abstract model (no database table) that provides the core
logic for serializing and deserializing records.
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
import base64
import gzip
import hashlib
from datetime import datetime

_logger = logging.getLogger(__name__)


class NumaSynchEngine(models.AbstractModel):
    """
    Abstract Synchronization Engine
    
    Defines the serialization protocol for converting Odoo records
    to/from a format suitable for synchronization.
    
    This is an abstract model - it does not create a database table.
    Other models can inherit from this to implement specific
    synchronization strategies.
    """
    _name = 'numa.synch.engine'
    _description = 'Abstract Synchronization Engine'

    def _serialize_record(self, record, sync_rule=None):
        """
        Serialize a single record to a dictionary format suitable for synchronization.
        
        This method converts an Odoo recordset (single record) into a tuple containing:
        - A dictionary of field values
        - A list of dependencies (related records that need to be synced first)
        
        :param recordset record: A single Odoo record (recordset with len=1)
        :param recordset sync_rule: Optional numa.synch.rule record for binary sync configuration
        :return: Tuple (vals_dict, dependencies_list)
                 - vals_dict: Dictionary of field values
                 - dependencies_list: List of records that this record depends on
        :rtype: tuple(dict, list)
        """
        if not record or len(record) != 1:
            raise ValidationError(_(
                '_serialize_record expects a single record, got %s records'
            ) % (len(record) if record else 0))
        
        record.ensure_one()
        
        vals_dict = {}
        dependencies_list = []
        
        # System fields to ignore
        system_fields = {
            'id', 'create_date', 'create_uid', 'write_date', 'write_uid',
            '__last_update', 'display_name', 'display_type',
        }
        
        # Get all fields for this model
        model_fields = record._fields
        
        for field_name, field in model_fields.items():
            # Skip system fields
            if field_name in system_fields:
                continue
            
            # Handle computed fields based on configuration
            if field.compute:
                # If sync_rule is provided, check if computed fields should be synced
                if sync_rule:
                    if not sync_rule.sync_computed_fields:
                        # Computed fields sync disabled
                        continue
                    # If stored, include it (will be synced directly)
                    # If not stored, skip serialization (will be recalculated on destination)
                    if not field.store:
                        # Non-stored computed fields are not serialized
                        # They will be recalculated on the destination
                        continue
                else:
                    # No sync_rule provided - default behavior: skip non-stored
                    if not field.store:
                        continue
            
            # Skip related fields (they will be handled through their base field)
            if field.related:
                continue
            
            try:
                field_value = record[field_name]
                
                # Handle Many2one fields
                if field.type == 'many2one':
                    if field_value:
                        # Convert to reference format
                        vals_dict[field_name] = {
                            '__type__': 'ref',
                            'model': field_value._name,
                            'id': field_value.id,
                        }
                        # Add to dependencies
                        dependencies_list.append(field_value)
                    else:
                        vals_dict[field_name] = False
                
                # Handle One2many and Many2many fields
                elif field.type in ('one2many', 'many2many'):
                    # For now, we'll serialize the IDs
                    # Future implementations might serialize the full records
                    if field_value:
                        vals_dict[field_name] = [
                            {
                                '__type__': 'ref',
                                'model': field.comodel_name,
                                'id': rec.id,
                            }
                            for rec in field_value
                        ]
                        # Add to dependencies
                        dependencies_list.extend(field_value)
                    else:
                        vals_dict[field_name] = []
                
                # Handle Date fields
                elif field.type == 'date':
                    if field_value:
                        # Convert to string format (YYYY-MM-DD)
                        vals_dict[field_name] = field_value.strftime('%Y-%m-%d') if hasattr(field_value, 'strftime') else str(field_value)
                    else:
                        vals_dict[field_name] = False
                
                # Handle Datetime fields
                elif field.type == 'datetime':
                    if field_value:
                        # Convert to ISO format string
                        if isinstance(field_value, datetime):
                            vals_dict[field_name] = field_value.isoformat()
                        else:
                            vals_dict[field_name] = str(field_value)
                    else:
                        vals_dict[field_name] = False
                
                # Handle Binary fields
                elif field.type == 'binary':
                    if sync_rule and sync_rule.sync_binary_fields:
                        # Check if binary field should be synced
                        binary_data = self._serialize_binary_field(
                            field_value,
                            sync_rule.binary_max_size_mb,
                            sync_rule.binary_compress
                        )
                        if binary_data:
                            vals_dict[field_name] = binary_data
                        else:
                            _logger.debug(
                                'Skipping binary field %s.%s (too large or empty)',
                                record._name, field_name
                            )
                    else:
                        _logger.debug(
                            'Skipping binary field %s.%s (binary sync disabled in rule)',
                            record._name, field_name
                        )
                    continue
                
                # Handle other field types (Char, Text, Integer, Float, Boolean, Selection, etc.)
                else:
                    vals_dict[field_name] = field_value
                    
            except Exception as e:
                _logger.warning(
                    'Error serializing field %s.%s: %s',
                    record._name, field_name, str(e)
                )
                # Continue with other fields
                continue
        
        return vals_dict, dependencies_list

    def _parse_incoming_ref(self, ref_dict, source_node):
        """
        Parse an incoming reference dictionary and return the local ID.
        
        This method looks up the local ID corresponding to a remote ID
        using the identity mapping table.
        
        :param dict ref_dict: Dictionary with format:
                            {'__type__': 'ref', 'model': '...', 'id': remote_id}
        :param str source_node: Node token of the source node (Slave UUID or 'MASTER')
        :return: Local ID (integer) or False if mapping not found
        :rtype: int or False
        """
        if not ref_dict or not isinstance(ref_dict, dict):
            return False
        
        if ref_dict.get('__type__') != 'ref':
            return False
        
        model_name = ref_dict.get('model')
        remote_id = ref_dict.get('id')
        
        if not model_name or not remote_id or not source_node:
            return False
        
        # Use the identity mapping table to find local ID
        synch_map = self.env['numa.synch.map']
        local_id = synch_map.get_local_id(model_name, remote_id, source_node)
        
        return local_id

    def _serialize_binary_field(self, binary_value, max_size_mb=10.0, compress=True):
        """
        Serialize a binary field value to a dictionary format.
        
        :param bytes binary_value: Binary data (can be base64 string or bytes)
        :param float max_size_mb: Maximum size in MB (default: 10.0)
        :param bool compress: Whether to compress the data (default: True)
        :return: Dictionary with binary data or None if too large/empty
        :rtype: dict or None
        """
        if not binary_value:
            return None
        
        # Convert to bytes if it's a base64 string
        if isinstance(binary_value, str):
            try:
                binary_data = base64.b64decode(binary_value)
            except Exception as e:
                _logger.warning('Error decoding base64 binary data: %s', str(e))
                return None
        elif isinstance(binary_value, bytes):
            binary_data = binary_value
        else:
            _logger.warning('Unexpected binary field type: %s', type(binary_value))
            return None
        
        # Check size limit
        size_mb = len(binary_data) / (1024 * 1024)
        if size_mb > max_size_mb:
            _logger.warning(
                'Binary field too large: %.2f MB (max: %.2f MB). Skipping.',
                size_mb, max_size_mb
            )
            return None
        
        # Compress if requested
        if compress:
            try:
                compressed_data = gzip.compress(binary_data)
                # Only use compression if it actually reduces size
                if len(compressed_data) < len(binary_data):
                    binary_data = compressed_data
                    is_compressed = True
                else:
                    is_compressed = False
            except Exception as e:
                _logger.warning('Error compressing binary data: %s', str(e))
                is_compressed = False
        else:
            is_compressed = False
        
        # Encode to base64 for JSON serialization
        base64_data = base64.b64encode(binary_data).decode('utf-8')
        
        return {
            '__type__': 'binary',
            'data': base64_data,
            'compressed': is_compressed,
            'size_bytes': len(binary_data) if not is_compressed else len(binary_data),
            'original_size_mb': size_mb,
        }

    def _deserialize_binary_field(self, binary_dict):
        """
        Deserialize a binary field dictionary back to binary data.
        
        :param dict binary_dict: Dictionary with format:
            {
                '__type__': 'binary',
                'data': 'base64_string',
                'compressed': True/False,
                ...
            }
        :return: Binary data (bytes) or None
        :rtype: bytes or None
        """
        if not binary_dict or not isinstance(binary_dict, dict):
            return None
        
        if binary_dict.get('__type__') != 'binary':
            return None
        
        base64_data = binary_dict.get('data')
        is_compressed = binary_dict.get('compressed', False)
        
        if not base64_data:
            return None
        
        try:
            # Decode from base64
            binary_data = base64.b64decode(base64_data)
            
            # Decompress if needed
            if is_compressed:
                try:
                    binary_data = gzip.decompress(binary_data)
                except Exception as e:
                    _logger.error('Error decompressing binary data: %s', str(e))
                    return None
            
            # Return as base64 string (Odoo format)
            return base64.b64encode(binary_data).decode('utf-8')
            
        except Exception as e:
            _logger.error('Error deserializing binary field: %s', str(e))
            return None

    def _get_system_metadata(self):
        """
        Generate system metadata for protocol validation.
        
        Returns a dictionary containing identifying information about the local instance:
        - odoo_version: Odoo server version (e.g., "18.0")
        - db_uuid: Database UUID
        - module_version: Installed version of numa_synch
        
        :return: Dictionary with system metadata
        :rtype: dict
        """
        try:
            import odoo
            odoo_version = odoo.service.common.exp_version()['server_version']
        except Exception:
            # Fallback if exp_version is not available
            odoo_version = self.env['ir.module.module'].search([
                ('name', '=', 'base')
            ], limit=1).latest_version or '18.0'
        
        db_uuid = self.env['ir.config_parameter'].sudo().get_param('database.uuid') or ''
        
        # Get module version
        module = self.env['ir.module.module'].search([
            ('name', '=', 'numa_synch')
        ], limit=1)
        module_version = module.latest_version if module else '18.0.1.0.0'
        
        return {
            'odoo_version': odoo_version,
            'db_uuid': db_uuid,
            'module_version': module_version,
        }

    def _compute_model_hash(self, model_name, sync_rule=None):
        """
        Calculate a deterministic SHA256 hash representing the current structure
        of the model restricted to whitelisted fields from sync rules.
        
        The hash is based on:
        - Field name
        - Field type
        - Required status
        - Relation (for relational fields)
        
        :param str model_name: Technical name of the model
        :param recordset sync_rule: Optional numa.synch.rule for field filtering
        :return: SHA256 hash string
        :rtype: str
        """
        try:
            model = self.env[model_name]
        except KeyError:
            _logger.warning('Model %s does not exist', model_name)
            return None
        
        model_fields = model._fields
        
        # System fields to exclude from hash
        system_fields = {
            'id', 'create_date', 'create_uid', 'write_date', 'write_uid',
            '__last_update', 'display_name', 'display_type',
        }
        
        # Build field signatures
        field_signatures = []
        
        for field_name, field in model_fields.items():
            # Skip system fields
            if field_name in system_fields:
                continue
            
            # Skip computed fields that are not stored (unless sync_rule allows)
            if field.compute and not field.store:
                if not sync_rule or not sync_rule.sync_computed_fields:
                    continue
            
            # Skip related fields
            if field.related:
                continue
            
            # Build signature: name:type:required:relation
            signature_parts = [
                field_name,
                field.type,
                str(field.required),
            ]
            
            # Add relation info for relational fields
            if field.type in ('many2one', 'one2many', 'many2many'):
                signature_parts.append(field.comodel_name or '')
            else:
                signature_parts.append('')
            
            signature = ':'.join(signature_parts)
            field_signatures.append(signature)
        
        # Sort signatures alphabetically for determinism
        field_signatures.sort()
        
        # Concatenate and hash
        concatenated = '\n'.join(field_signatures)
        hash_obj = hashlib.sha256(concatenated.encode('utf-8'))
        
        return hash_obj.hexdigest()

    def _validate_metadata(self, incoming_meta, active_models):
        """
        Validate incoming metadata against local system.
        
        Performs:
        1. Version check (Odoo version must match)
        2. DB UUID check (optional, logs warning if different)
        3. Schema check (model hashes must match)
        
        :param dict incoming_meta: Metadata dictionary from incoming JSON
        :param list active_models: List of model names in the batch
        :raises UserError: If validation fails
        """
        if not incoming_meta:
            raise UserError(_('Metadata is required for synchronization'))
        
        # Get local system metadata
        local_meta = self._get_system_metadata()
        
        # 1. Version Check
        incoming_version = incoming_meta.get('system', {}).get('odoo_version')
        if incoming_version != local_meta['odoo_version']:
            raise UserError(_(
                'Version Mismatch: Remote Odoo version (%s) does not match '
                'local version (%s). Synchronization requires identical Odoo versions.'
            ) % (incoming_version, local_meta['odoo_version']))
        
        # 2. DB UUID Check (Optional - just log)
        incoming_db_uuid = incoming_meta.get('system', {}).get('db_uuid')
        if incoming_db_uuid and incoming_db_uuid != local_meta['db_uuid']:
            _logger.info(
                'Database UUID differs: Remote=%s, Local=%s (This is expected for different databases)',
                incoming_db_uuid, local_meta['db_uuid']
            )
        
        # 3. Schema Check
        incoming_models = incoming_meta.get('models', {})
        
        if not incoming_models:
            _logger.warning('No model hashes in incoming metadata')
            return
        
        # Get sync rules for models to determine which fields to include
        rules_by_model = {}
        for rule in self.env['numa.synch.rule'].search([
            ('active', '=', True),
            ('model_name', 'in', active_models)
        ]):
            if rule.model_name:
                rules_by_model[rule.model_name] = rule
        
        for model_name in active_models:
            if model_name not in incoming_models:
                _logger.warning(
                    'Model %s not found in incoming metadata hashes',
                    model_name
                )
                continue
            
            incoming_hash = incoming_models[model_name]
            
            # Get sync rule for this model (if available)
            sync_rule = rules_by_model.get(model_name)
            
            # Calculate local hash
            local_hash = self._compute_model_hash(model_name, sync_rule)
            
            if not local_hash:
                _logger.warning(
                    'Could not compute hash for model %s',
                    model_name
                )
                continue
            
            if incoming_hash != local_hash:
                raise UserError(_(
                    'Schema Mismatch in model %s.\n'
                    'Remote hash: %s\n'
                    'Local hash: %s\n\n'
                    'This indicates that the model structure differs between '
                    'the Slave and Master. Ensure both servers have the same '
                    'modules installed and the same field definitions.'
                ) % (model_name, incoming_hash[:16], local_hash[:16]))
