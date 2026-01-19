"""
Abstract Synchronization Engine

This model defines the serialization protocol for synchronization.
It is an abstract model (no database table) that provides the core
logic for serializing and deserializing records.
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
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

    def _serialize_record(self, record):
        """
        Serialize a single record to a dictionary format suitable for synchronization.
        
        This method converts an Odoo recordset (single record) into a tuple containing:
        - A dictionary of field values
        - A list of dependencies (related records that need to be synced first)
        
        :param recordset record: A single Odoo record (recordset with len=1)
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
            
            # Skip computed fields that are not stored
            if field.compute and not field.store:
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
                
                # Handle Binary fields - skip for now (performance)
                elif field.type == 'binary':
                    _logger.debug(
                        'Skipping binary field %s.%s for performance reasons',
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
