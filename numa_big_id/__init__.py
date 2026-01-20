# -*- coding: utf-8 -*-
"""
Numa Big ID Module

This module converts all integer (int4) columns to BIGINT (int8) in PostgreSQL
to support infinite scalability for polymorphic models.

The monkey patch is applied immediately when this module is loaded to ensure
that all new Integer fields created after installation will be BIGINT.
"""

# Import the patch module to apply monkey patches immediately
# This ensures that all Integer fields created after module load will be BIGINT
try:
    from . import models
except ImportError:
    # If models can't be imported (e.g., during initial installation),
    # the patch will be applied when the module is fully loaded
    pass
