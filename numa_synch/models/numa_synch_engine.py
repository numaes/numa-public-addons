"""
Abstract Synchronization Engine

This model defines the serialization protocol for synchronization.
It is an abstract model (no database table) that provides the core
logic for serializing and deserializing records.
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
import base64
import gzip
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
