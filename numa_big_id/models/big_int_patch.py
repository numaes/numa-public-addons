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


class SubscriptableLazyProperty:
    """
    A descriptor that mimics lazy_property but ensures the value is always
    a tuple that supports subscript operations.
    
    The key difference from lazy_property is that we ensure the cached value
    is always a tuple, so subscript operations like [1] work correctly.
    """
    def __init__(self, fget):
        self.fget = fget
        # Store the attribute name for caching
        self.attrname = fget.__name__
    
    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        # Check if already cached using __dict__ to avoid recursion
        # Using __dict__ directly prevents triggering the descriptor again
        if self.attrname in obj.__dict__:
            cached = obj.__dict__[self.attrname]
            _logger.debug("SubscriptableLazyProperty: Returning cached value for %s.%s: %s", 
                         type(obj).__name__, self.attrname, cached)
            return cached
        # Evaluate the property
        _logger.debug("SubscriptableLazyProperty: Evaluating %s.%s", 
                     type(obj).__name__, self.attrname)
        value = self.fget(obj)
        # Ensure it's a tuple
        if not isinstance(value, (tuple, list)):
            value = (value, value) if value else None
        else:
            value = tuple(value)
        # Cache it on the instance using __dict__ to avoid recursion
        obj.__dict__[self.attrname] = value
        _logger.debug("SubscriptableLazyProperty: Cached value for %s.%s: %s", 
                     type(obj).__name__, self.attrname, value)
        return value
    
    def reset_all(self, obj):
        """Reset the cached value on the object."""
        if self.attrname in obj.__dict__:
            del obj.__dict__[self.attrname]


def column_type(self):
    """
    Override column_type property to return BIGINT instead of integer.
    
    This ensures that when Odoo creates a column for an Integer field,
    it will use BIGINT (int8) instead of the default integer (int4).
    
    Note: The function name must be 'column_type' for lazy_property to work correctly.
    lazy_property uses fget.__name__ to cache the value on the instance.
    """
    # Call the original method to get the base column type
    # For Integer fields, this typically returns ('int4', 'int4')
    try:
        if hasattr(self, '_original_get_column_type'):
            original_getter = self._original_get_column_type
            # If it's a callable (function), call it with self
            if callable(original_getter):
                original_type = original_getter(self)
            else:
                # If it's stored as a value, use it directly
                original_type = original_getter
        else:
            # Fallback: return default integer type (int4 in Odoo)
            original_type = ('int4', 'int4')
    except Exception as e:
        _logger.debug("Error getting original column_type: %s", e)
        original_type = ('int4', 'int4')
    
    # If it's an integer type (int4), convert to bigint (int8)
    # Check if original_type is a tuple/list with at least 2 elements
    if isinstance(original_type, (tuple, list)) and len(original_type) >= 2:
        sql_type, pg_type = original_type[0], original_type[1]
        
        # Replace int4 with int8 (bigint)
        if pg_type in ('int4', 'integer'):
            # Logging removed per user request - too verbose
            return ('int8', 'bigint')
    
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
    # We need to get the original getter before replacing the descriptor
    if hasattr(fields.Integer, 'column_type'):
        if not hasattr(fields.Integer, '_original_get_column_type'):
            # Access the descriptor at class level - it will return itself
            original_column_type_descriptor = fields.Integer.column_type
            
            # Check if it's a lazy_property (Odoo 18)
            if hasattr(original_column_type_descriptor, 'fget'):
                # It's a lazy_property - get the underlying function
                original_getter = original_column_type_descriptor.fget
                if original_getter:
                    # Store the getter directly - it will be called with self by the descriptor
                    # The getter from lazy_property already expects (self) as argument
                    fields.Integer._original_get_column_type = original_getter
                else:
                    def _default_get_column_type(self):
                        return ('int4', 'int4')
                    fields.Integer._original_get_column_type = _default_get_column_type
            elif isinstance(original_column_type_descriptor, property):
                # It's a regular property - get the getter
                original_getter = original_column_type_descriptor.fget
                if original_getter:
                    # Store the getter directly - it already expects (self) as argument
                    fields.Integer._original_get_column_type = original_getter
                else:
                    def _default_get_column_type(self):
                        return ('int4', 'int4')
                    fields.Integer._original_get_column_type = _default_get_column_type
            else:
                # If it's not a property/lazy_property, it's a direct value
                # This shouldn't happen for column_type, but handle it anyway
                def _get_direct_value(self):
                    return original_column_type_descriptor
                fields.Integer._original_get_column_type = _get_direct_value
    
    # Patch column_type property
    try:
        # Replace the column_type property with our patched version
        # We need to use a custom descriptor that supports subscript
        # because Odoo sometimes accesses field.column_type[1] directly
        old_descriptor = fields.Integer.column_type
        fields.Integer.column_type = SubscriptableLazyProperty(column_type)
        _logger.info("Patched fields.Integer.column_type to return BIGINT (was: %s)", 
                    type(old_descriptor).__name__)
        # Verify the patch
        if isinstance(fields.Integer.column_type, SubscriptableLazyProperty):
            _logger.debug("✓ Verified: fields.Integer.column_type is now SubscriptableLazyProperty")
        else:
            _logger.warning("✗ Warning: fields.Integer.column_type is %s, not SubscriptableLazyProperty", 
                          type(fields.Integer.column_type).__name__)
    except Exception as e:
        _logger.warning("Could not patch column_type property: %s", e, exc_info=True)
    
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
                # Access the descriptor at class level - it will return itself
                original_column_type_descriptor = fields.Many2one.column_type
                
                # Check if it's a lazy_property (Odoo 18)
                if hasattr(original_column_type_descriptor, 'fget'):
                    # It's a lazy_property - get the underlying function
                    original_getter = original_column_type_descriptor.fget
                    if original_getter:
                        # Store the getter directly - it will be called with self by the descriptor
                        fields.Many2one._original_get_column_type = original_getter
                    else:
                        def _default_get_column_type(self):
                            return ('int4', 'int4')
                        fields.Many2one._original_get_column_type = _default_get_column_type
                elif isinstance(original_column_type_descriptor, property):
                    # It's a regular property - get the getter
                    original_getter = original_column_type_descriptor.fget
                    if original_getter:
                        # Store the getter directly - it already expects (self) as argument
                        fields.Many2one._original_get_column_type = original_getter
                    else:
                        def _default_get_column_type(self):
                            return ('int4', 'int4')
                        fields.Many2one._original_get_column_type = _default_get_column_type
                else:
                    # If it's not a property/lazy_property, it's a direct value
                    def _get_direct_value(self):
                        return original_column_type_descriptor
                    fields.Many2one._original_get_column_type = _get_direct_value
            
            # Apply same patch to Many2one
            # We need to use a custom descriptor that supports subscript
            fields.Many2one.column_type = SubscriptableLazyProperty(column_type)
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
