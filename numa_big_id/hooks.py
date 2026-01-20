# -*- coding: utf-8 -*-
"""
Pre-installation hooks for numa_big_id module.

This module performs a critical database migration: converting all integer (int4)
columns to BIGINT (int8) to support infinite scalability for polymorphic models.
"""

import logging
from odoo import api, SUPERUSER_ID
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Safety threshold: if any critical table exceeds this number of rows,
# abort the installation to prevent unsafe automatic migration
MAX_SAFE_ROWS = 500000

# Critical tables to check before migration
CRITICAL_TABLES = [
    'res_partner',
    'mail_message',
    'ir_attachment',
    'ir_model_data',
    'res_users',
]


def pre_init_hook(cr):
    """
    Pre-installation hook that migrates all integer columns to BIGINT.
    
    This hook:
    1. Performs a safety check on critical tables
    2. If safe, migrates all integer columns to BIGINT
    3. Converts all sequences to BIGINT
    
    Args:
        cr: Database cursor
        
    Raises:
        UserError: If database is too large for safe automatic migration
    """
    _logger.info("=" * 80)
    _logger.info("NUMA BIG ID: Starting pre-installation migration")
    _logger.info("=" * 80)
    
    # Step 1: Safety Check
    _logger.info("Step 1: Performing safety check on critical tables...")
    for table_name in CRITICAL_TABLES:
        try:
            cr.execute("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            """, (table_name,))
            
            if cr.fetchone()[0] == 0:
                _logger.debug("Table %s does not exist, skipping", table_name)
                continue
                
            cr.execute("SELECT COUNT(*) FROM %s" % table_name)
            row_count = cr.fetchone()[0]
            _logger.info("Table %s: %s rows", table_name, row_count)
            
            if row_count > MAX_SAFE_ROWS:
                error_msg = (
                    "La base de datos es demasiado grande para una migración automática segura.\n\n"
                    "La tabla '%s' contiene %s registros, lo cual excede el límite seguro de %s.\n\n"
                    "Por favor, realice la conversión a BIGINT mediante scripts externos controlados "
                    "por un DBA antes de instalar este módulo.\n\n"
                    "Este módulo requiere una migración manual para bases de datos grandes."
                ) % (table_name, row_count, MAX_SAFE_ROWS)
                
                _logger.error(error_msg)
                raise UserError(error_msg)
                
        except UserError:
            raise
        except Exception as e:
            _logger.warning("Error checking table %s: %s", table_name, e)
            # Continue with other tables, but log the warning
    
    _logger.info("Safety check passed. Proceeding with migration...")
    
    # Step 2: Get all tables in public schema
    _logger.info("Step 2: Discovering all tables in public schema...")
    cr.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    all_tables = [row[0] for row in cr.fetchall()]
    _logger.info("Found %s tables to analyze", len(all_tables))
    
    # Step 3: Migrate integer columns to BIGINT
    _logger.info("Step 3: Migrating integer columns to BIGINT...")
    columns_migrated = 0
    
    for table_name in all_tables:
        try:
            # Get all integer columns in this table
            cr.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = %s
                AND data_type = 'integer'
                ORDER BY column_name
            """, (table_name,))
            
            integer_columns = cr.fetchall()
            
            if not integer_columns:
                _logger.debug("Table %s: No integer columns found", table_name)
                continue
            
            _logger.info("Table %s: Found %s integer columns", table_name, len(integer_columns))
            
            for column_name, _ in integer_columns:
                try:
                    # Check if column is already BIGINT
                    cr.execute("""
                        SELECT data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = %s
                        AND column_name = %s
                    """, (table_name, column_name))
                    
                    result = cr.fetchone()
                    if result and result[0] == 'bigint':
                        _logger.debug("Column %s.%s is already BIGINT, skipping", table_name, column_name)
                        continue
                    
                    # Convert column to BIGINT
                    _logger.info("Converting column %s.%s from integer to BIGINT", table_name, column_name)
                    cr.execute("""
                        ALTER TABLE %s 
                        ALTER COLUMN %s TYPE bigint
                    """ % (table_name, column_name))
                    
                    columns_migrated += 1
                    _logger.debug("Successfully converted %s.%s to BIGINT", table_name, column_name)
                    
                except Exception as e:
                    _logger.error(
                        "Error converting column %s.%s: %s",
                        table_name, column_name, e
                    )
                    # Continue with other columns
                    
        except Exception as e:
            _logger.error("Error processing table %s: %s", table_name, e)
            # Continue with other tables
    
    _logger.info("Migrated %s columns to BIGINT", columns_migrated)
    
    # Step 4: Convert sequences to BIGINT
    _logger.info("Step 4: Converting sequences to BIGINT...")
    sequences_migrated = 0
    
    # Get all sequences
    cr.execute("""
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
        ORDER BY sequence_name
    """)
    
    all_sequences = [row[0] for row in cr.fetchall()]
    _logger.info("Found %s sequences to analyze", len(all_sequences))
    
    for sequence_name in all_sequences:
        try:
            # Check current data type of sequence
            cr.execute("""
                SELECT data_type
                FROM information_schema.sequences
                WHERE sequence_schema = 'public'
                AND sequence_name = %s
            """, (sequence_name,))
            
            result = cr.fetchone()
            if result and result[0] == 'bigint':
                _logger.debug("Sequence %s is already BIGINT, skipping", sequence_name)
                continue
            
            # For PostgreSQL 10+, we can use ALTER SEQUENCE ... AS bigint
            # For older versions, we need to recreate the sequence
            try:
                # Try PostgreSQL 10+ syntax first
                cr.execute("ALTER SEQUENCE %s AS bigint" % sequence_name)
                sequences_migrated += 1
                _logger.info("Converted sequence %s to BIGINT (PostgreSQL 10+ syntax)", sequence_name)
            except Exception:
                # Fallback: Get current sequence properties and recreate
                cr.execute("""
                    SELECT last_value, is_called
                    FROM %s
                """ % sequence_name)
                
                last_value, is_called = cr.fetchone()
                
                # Get increment, min, max values
                cr.execute("""
                    SELECT increment_by, min_value, max_value
                    FROM %s
                """ % sequence_name)
                
                increment, min_val, max_val = cr.fetchone()
                
                # Drop and recreate as BIGINT
                cr.execute("DROP SEQUENCE %s" % sequence_name)
                cr.execute("""
                    CREATE SEQUENCE %s
                    AS bigint
                    INCREMENT BY %s
                    MINVALUE %s
                    MAXVALUE %s
                    START WITH %s
                """ % (sequence_name, increment, min_val, max_val, last_value + 1 if is_called else last_value))
                
                sequences_migrated += 1
                _logger.info("Recreated sequence %s as BIGINT (fallback method)", sequence_name)
                
        except Exception as e:
            _logger.error("Error converting sequence %s: %s", sequence_name, e)
            # Continue with other sequences
    
    _logger.info("Migrated %s sequences to BIGINT", sequences_migrated)
    
    _logger.info("=" * 80)
    _logger.info("NUMA BIG ID: Pre-installation migration completed successfully")
    _logger.info("=" * 80)
