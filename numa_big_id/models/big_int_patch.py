# -*- coding: utf-8 -*-
"""
Monkey patch for Odoo ORM to force Integer fields to map to BIGINT.

This patch modifies the behavior of odoo.fields.Integer (and by inheritance
fields.Id) to ensure that all Integer fields are created as BIGINT (int8) in
PostgreSQL instead of the default integer (int4).

This is critical for polymorphic models that unify sequences, as they will
quickly exhaust the 2.147 billion record limit of int4.

The patch is applied at module load time and affects:
- fields.Integer: Base integer field type
- fields.Id: ID field (inherits from Integer)
- fields.Many2one: Foreign key fields (use Integer internally)
- fields.Many2many: Relation table columns (created dynamically)
"""

import logging
from odoo import fields
from odoo.tools.func import lazy_property

_logger = logging.getLogger(__name__)


def column_type(self):
    """
    Override column_type property to return BIGINT instead of integer.
    
    This ensures that when Odoo creates a column for an Integer field,
    it will use BIGINT (int8) instead of the default integer (int4).
    
    Note: The function name must be 'column_type' for lazy_property to work correctly.
    """
    # Call the original method to get the base column type
    # For Integer fields, this typically returns ('integer', 'integer')
    try:
        if hasattr(self, '_original_get_column_type'):
            original_getter = self._original_get_column_type
            # If it's a callable (function), call it
            if callable(original_getter):
                # Try calling with self first (normal case)
                try:
                    original_type = original_getter(self)
                except TypeError:
                    # If that fails, try calling without self (for lambdas that don't need it)
                    try:
                        original_type = original_getter()
                    except TypeError:
                        # Last resort: return default
                        original_type = ('integer', 'integer')
            else:
                # If it's stored as a value, use it directly
                original_type = original_getter
        else:
            # Fallback: return default integer type
            original_type = ('integer', 'integer')
    except Exception as e:
        _logger.debug("Error getting original column_type: %s", e)
        original_type = ('integer', 'integer')
    
    # If it's an integer type, convert to bigint
    # Check if original_type is a tuple/list with at least 2 elements
    if isinstance(original_type, (tuple, list)) and len(original_type) >= 2:
        sql_type, pg_type = original_type[0], original_type[1]
        
        # Replace integer with bigint
        if pg_type == 'integer':
            # Only log at INFO level for ID fields, DEBUG for others
            if hasattr(self, 'name') and self.name == 'id':
                _logger.info(
                    "Patching column_type for ID field %s: integer -> bigint",
                    self.name
                )
            else:
                _logger.debug(
                    "Patching column_type for field %s: integer -> bigint",
                    self.name if hasattr(self, 'name') else 'unknown'
                )
            return (sql_type, 'bigint')
    
    return original_type


def _process_column_type_bigint(self, column_type):
    """
    Override _process_column_type to ensure BIGINT is used.
    
    This method is called during table creation to process the column type.
    We ensure that integer types are converted to bigint.
    """
    # Call original method first
    result = self._original_process_column_type(column_type)
    
    # If result contains 'integer', replace with 'bigint'
    if isinstance(result, str):
        if 'integer' in result.lower() and 'bigint' not in result.lower():
            _logger.debug(
                "Patching _process_column_type for field %s: integer -> bigint",
                self.name if hasattr(self, 'name') else 'unknown'
            )
            return result.replace('integer', 'bigint').replace('INTEGER', 'BIGINT')
    
    return result


def apply_bigint_patch():
    """
    Apply monkey patches to Odoo's Integer field class.
    
    This function patches the Integer field class to force all integer
    columns to be created as BIGINT in PostgreSQL.
    """
    _logger.info("Applying BIGINT patch to Odoo ORM...")
    
    # Store original methods if they exist
    if hasattr(fields.Integer, 'column_type'):
        if not hasattr(fields.Integer, '_original_get_column_type'):
            # Store original column_type property
            if isinstance(fields.Integer.column_type, property):
                # Get the original getter
                original_getter = fields.Integer.column_type.fget
                if original_getter:
                    fields.Integer._original_get_column_type = original_getter
                else:
                    # If no getter, create a default one
                    def _default_get_column_type(self):
                        return ('integer', 'integer')
                    fields.Integer._original_get_column_type = _default_get_column_type
            else:
                # If it's not a property, it's a direct value - create a getter that returns it
                # Store the value directly and create a simple getter
                original_value = fields.Integer.column_type
                def _get_direct_value(self):
                    return original_value
                fields.Integer._original_get_column_type = _get_direct_value
    
    # Patch column_type property
    try:
        # Replace the column_type property with our patched version
        # Use lazy_property to match Odoo's expected behavior
        # The function name must be 'column_type' for lazy_property to cache correctly
        fields.Integer.column_type = lazy_property(column_type)
        _logger.info("Patched fields.Integer.column_type to return BIGINT")
    except Exception as e:
        _logger.warning("Could not patch column_type property: %s", e)
    
    # Patch _process_column_type if it exists
    if hasattr(fields.Integer, '_process_column_type'):
        if not hasattr(fields.Integer, '_original_process_column_type'):
            fields.Integer._original_process_column_type = fields.Integer._process_column_type
        
        fields.Integer._process_column_type = _process_column_type_bigint
        _logger.info("Patched fields.Integer._process_column_type to use BIGINT")
    else:
        _logger.debug("fields.Integer._process_column_type not found, skipping patch")
    
    # Ensure Many2one fields also use BIGINT
    # Many2one fields internally use Integer for foreign keys
    if hasattr(fields.Many2one, 'column_type'):
        try:
            # Store original if not already stored
            if not hasattr(fields.Many2one, '_original_get_column_type'):
                original_column_type = fields.Many2one.column_type
                
                # Check if it's a lazy_property (Odoo 18)
                if hasattr(original_column_type, 'func'):
                    # It's a lazy_property - get the underlying function
                    original_getter = original_column_type.func
                    if original_getter:
                        def _wrapped_original(self):
                            return original_getter(self)
                        fields.Many2one._original_get_column_type = _wrapped_original
                    else:
                        def _default_get_column_type(self):
                            return ('integer', 'integer')
                        fields.Many2one._original_get_column_type = _default_get_column_type
                elif isinstance(original_column_type, property):
                    # It's a regular property - get the getter
                    original_getter = original_column_type.fget
                    if original_getter:
                        def _wrapped_original(self):
                            return original_getter(self)
                        fields.Many2one._original_get_column_type = _wrapped_original
                    else:
                        def _default_get_column_type(self):
                            return ('integer', 'integer')
                        fields.Many2one._original_get_column_type = _default_get_column_type
                else:
                    # If it's not a property/lazy_property, it's a direct value
                    def _get_direct_value(self):
                        return original_column_type
                    fields.Many2one._original_get_column_type = _get_direct_value
            
            # Apply same patch to Many2one
            # Use lazy_property to match Odoo's expected behavior
            # The function name must be 'column_type' for lazy_property to cache correctly
            fields.Many2one.column_type = lazy_property(column_type)
            _logger.info("Patched fields.Many2one.column_type to return BIGINT")
        except Exception as e:
            _logger.warning("Could not patch Many2one.column_type: %s", e)
    
    # Patch Many2many relation table creation
    # Many2many fields create relation tables dynamically, and we need to ensure
    # those tables use BIGINT for their foreign key columns
    if hasattr(fields.Many2many, '_update_relation_table'):
        original_update = fields.Many2many._update_relation_table
        if not hasattr(fields.Many2many, '_original_update_relation_table'):
            fields.Many2many._original_update_relation_table = original_update
        
        def _update_relation_table_bigint(self, cr):
            """Patched version that ensures BIGINT columns in relation tables."""
            # Call original method
            result = self._original_update_relation_table(cr)
            
            # After table creation, ensure columns are BIGINT
            if hasattr(self, 'relation_table'):
                table_name = self.relation_table
                try:
                    # Check and convert columns to BIGINT
                    cr.execute("""
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = %s
                        AND data_type = 'integer'
                    """, (table_name,))
                    
                    integer_columns = cr.fetchall()
                    for column_name, _ in integer_columns:
                        try:
                            cr.execute("""
                                ALTER TABLE %s 
                                ALTER COLUMN %s TYPE bigint
                            """ % (table_name, column_name))
                            _logger.debug(
                                "Converted Many2many relation column %s.%s to BIGINT",
                                table_name, column_name
                            )
                        except Exception as e:
                            _logger.warning(
                                "Could not convert %s.%s to BIGINT: %s",
                                table_name, column_name, e
                            )
                except Exception as e:
                    _logger.warning("Error checking relation table %s: %s", table_name, e)
            
            return result
        
        fields.Many2many._update_relation_table = _update_relation_table_bigint
        _logger.info("Patched fields.Many2many._update_relation_table to use BIGINT")
    
    _logger.info("BIGINT patch applied successfully")


# Apply the patch when this module is imported
apply_bigint_patch()
