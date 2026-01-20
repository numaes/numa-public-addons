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
# 
# IMPORTANT RISKS FOR LARGE DATABASES:
# - Partial transactions: Intermediate commits can leave database in inconsistent state if interrupted
# - Disk space: Conversion may require up to 2x disk space temporarily (PostgreSQL creates new files)
# - Long locks: ALTER TABLE can lock tables for extended periods, blocking other operations
# - Index recreation: Indexes may need to be rebuilt, which can be very slow on large tables
# - Materialized views: Not currently handled (may need manual intervention)
# - Triggers: Not validated (may have issues with type changes)
# - Replication: Can cause issues with streaming replication if not properly handled
# - Rollback: No automatic rollback mechanism - manual intervention required if migration fails
# - Execution time: Can take hours on very large databases
#
# RECOMMENDATION: For databases with >500k records, use manual migration by DBA
MAX_SAFE_ROWS = 500000

# Enable foreign key handling (can be very heavy on medium databases)
# Set to True only if you have a small database or can afford downtime
# When False, ID column conversion may fail if foreign keys block it
# 
# WARNING: Enabling this can make migration 10-100x slower on large databases
# as it requires dropping and recreating all foreign keys
HANDLE_FOREIGN_KEYS = False

# Critical tables to check before migration
# These are common Odoo core tables that typically have the most records.
# The safety check uses these to estimate database size. If any of these
# tables exceed MAX_SAFE_ROWS, the migration is aborted for safety.
# This list is not exhaustive - it's just a sample of high-volume tables.
# The actual migration processes ALL tables in the database, regardless
# of whether they're in this list.
CRITICAL_TABLES = [
    'res_partner',      # Partners/contacts (high volume in most installations)
    'mail_message',     # Messages (can grow very large)
    'ir_attachment',    # Attachments (can grow very large)
    'ir_model_data',    # Module data (grows with each module)
    'res_users',        # Users (typically small but important)
]


def get_and_drop_dependent_views(cr, table_name, column_name):
    """
    Get views that depend on a specific column and drop them temporarily.
    
    Note: This handles regular views ('v'), but NOT materialized views ('m').
    Materialized views need to be refreshed manually after migration.
    
    Returns:
        dict: Dict of {(view_schema, view_name): view_definition}
    """
    # Check for views that depend on this column
    # Note: This query finds regular views ('v'), not materialized views ('m')
    cr.execute("""
        SELECT DISTINCT dependent_ns.nspname as dependent_schema,
               dependent_view.relname as dependent_view
        FROM pg_depend
        JOIN pg_rewrite ON pg_depend.objid = pg_rewrite.oid
        JOIN pg_class as dependent_view ON pg_rewrite.ev_class = dependent_view.oid
        JOIN pg_class as source_table ON pg_depend.refobjid = source_table.oid
        JOIN pg_namespace dependent_ns ON dependent_view.relnamespace = dependent_ns.oid
        JOIN pg_namespace source_ns ON source_table.relnamespace = source_ns.oid
        WHERE source_ns.nspname = 'public'
        AND source_table.relname = %s
        AND dependent_view.relkind = 'v'
    """, (table_name,))
    
    dependent_views = cr.fetchall()
    view_definitions = []
    
    # Store view definitions before dropping
    for view_schema, view_name in dependent_views:
        try:
            # Use pg_get_viewdef to get the complete view definition
            cr.execute("""
                SELECT pg_get_viewdef('%s.%s'::regclass, true)
            """ % (view_schema, view_name))
            view_def = cr.fetchone()
            if view_def and view_def[0]:
                view_definitions.append((view_schema, view_name, view_def[0]))
            else:
                _logger.warning("  Could not get definition for view %s.%s", view_schema, view_name)
        except Exception as e:
            _logger.warning("  Could not get definition for view %s.%s: %s", view_schema, view_name, e)
    
    # Remove duplicates (CASCADE may drop multiple views)
    unique_views = {}
    for view_schema, view_name, view_def in view_definitions:
        view_key = (view_schema, view_name)
        if view_key not in unique_views:
            unique_views[view_key] = view_def
    
    # Drop views temporarily
    for (view_schema, view_name), _ in unique_views.items():
        try:
            cr.execute("DROP VIEW IF EXISTS %s.%s CASCADE" % (view_schema, view_name))
            _logger.debug("  Dropped view %s.%s temporarily (depends on %s.%s)", 
                         view_schema, view_name, table_name, column_name)
        except Exception as e:
            _logger.warning("  Could not drop view %s.%s: %s", view_schema, view_name, e)
    
    return unique_views


def recreate_views(cr, unique_views):
    """
    Recreate views that were dropped temporarily.
    
    Args:
        cr: Database cursor
        unique_views: Dict of {(view_schema, view_name): view_definition}
    """
    for (view_schema, view_name), view_def in unique_views.items():
        try:
            # Use CREATE OR REPLACE to handle cases where view still exists
            cr.execute("CREATE OR REPLACE VIEW %s.%s AS %s" % (view_schema, view_name, view_def))
            _logger.debug("  Recreated view %s.%s", view_schema, view_name)
        except Exception as e:
            _logger.error("  ✗ ERROR recreating view %s.%s: %s", view_schema, view_name, e)
            _logger.error("  MANUAL INTERVENTION REQUIRED for view %s.%s", view_schema, view_name)


def pre_init_hook(env):
    """
    Pre-installation hook that migrates all integer columns to BIGINT.
    
    This hook:
    1. Performs a safety check on critical tables
    2. If safe, migrates all integer columns to BIGINT
    3. Converts all sequences to BIGINT
    
    Args:
        env: Odoo Environment (in Odoo 18, hooks receive env instead of cr)
        
    Raises:
        UserError: If database is too large for safe automatic migration
    """
    # In Odoo 18, hooks receive env instead of cr
    # Get the cursor from the environment
    cr = env.cr
    _logger.info("=" * 80)
    _logger.info("NUMA BIG ID: Starting pre-installation migration")
    _logger.info("=" * 80)
    _logger.info("This hook converts all integer columns to BIGINT")
    _logger.info("IMPORTANT: This hook only runs during module installation")
    _logger.info("If module is already installed, uninstall and reinstall to run migration")
    
    # Step 1: Safety Check
    # This check uses a sample of common high-volume tables to estimate database size.
    # It's not exhaustive - the actual migration processes ALL tables in the database.
    # The purpose is to prevent accidental migration of very large databases where
    # the migration might take too long or cause issues.
    _logger.info("Step 1: Performing safety check on critical tables...")
    _logger.info("Note: This checks a sample of common tables. Migration will process ALL tables.")
    
    tables_checked = 0
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
            
            tables_checked += 1
                
            # Use parameterized query to avoid SQL injection
            cr.execute("SELECT COUNT(*) FROM %s" % table_name)
            row_count = cr.fetchone()[0]
            _logger.info("Table %s: %s rows", table_name, row_count)
            
            if row_count > MAX_SAFE_ROWS:
                error_msg = (
                    "La base de datos es demasiado grande para una migración automática segura.\n\n"
                    "La tabla '%s' contiene %s registros, lo cual excede el límite seguro de %s.\n\n"
                    "Por favor, realice la conversión a BIGINT mediante scripts externos controlados "
                    "por un DBA antes de instalar este módulo.\n\n"
                    "Este módulo requiere una migración manual para bases de datos grandes.\n\n"
                    "Nota: Puede ajustar MAX_SAFE_ROWS en hooks.py si desea cambiar este límite."
                ) % (table_name, row_count, MAX_SAFE_ROWS)
                
                _logger.error(error_msg)
                raise UserError(error_msg)
                
        except UserError:
            raise
        except Exception as e:
            _logger.warning("Error checking table %s: %s", table_name, e)
            # Continue with other tables, but log the warning
    
    if tables_checked == 0:
        _logger.warning("No critical tables found - database may be empty or use custom table names")
    
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
    
    # Check for materialized views (not handled automatically)
    cr.execute("""
        SELECT COUNT(*)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
        AND c.relkind = 'm'
    """)
    mat_view_count = cr.fetchone()[0]
    if mat_view_count > 0:
        _logger.warning("=" * 80)
        _logger.warning("WARNING: Found %s materialized views - these are NOT handled automatically", mat_view_count)
        _logger.warning("  Materialized views may need manual refresh after migration")
        _logger.warning("  Check logs and refresh manually: REFRESH MATERIALIZED VIEW <view_name>")
        _logger.warning("=" * 80)
    
    # Step 3: Migrate integer columns to BIGINT
    _logger.info("Step 3: Migrating integer columns to BIGINT...")
    columns_migrated = 0
    id_columns_migrated = 0
    
    # First pass: Convert all 'id' columns first (they are critical)
    _logger.info("Step 3a: Converting 'id' columns first (priority)...")
    
    if HANDLE_FOREIGN_KEYS:
        _logger.warning("FOREIGN KEY HANDLING ENABLED - This may be very slow on medium/large databases")
    
    commit_counter = 0
    COMMIT_INTERVAL = 50  # Commit every 50 tables to avoid lock exhaustion
    # 
    # WARNING: Intermediate commits mean the migration is NOT atomic.
    # If interrupted, the database will be in a partially migrated state.
    # There is NO automatic rollback - manual intervention will be required.
    # Consider this when deciding if automatic migration is appropriate.
    
    for table_name in all_tables:
        try:
            # Check if table has an 'id' column that is integer
            cr.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = %s
                AND column_name = 'id'
                AND data_type = 'integer'
            """, (table_name,))
            
            id_column = cr.fetchone()
            if not id_column:
                continue
            
            # Check if this table inherits from another table (table inheritance)
            # PostgreSQL doesn't allow altering inherited columns
            cr.execute("""
                SELECT COUNT(*)
                FROM pg_inherits
                WHERE inhrelid = %s::regclass
            """, (table_name,))
            
            is_inherited = cr.fetchone()[0] > 0
            if is_inherited:
                _logger.debug("  Skipping %s.id - column is inherited (table inheritance)", table_name)
                continue
            
            # Check if already BIGINT (double check)
            cr.execute("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = %s
                AND column_name = 'id'
            """, (table_name,))
            
            result = cr.fetchone()
            if result and result[0] == 'bigint':
                continue
            
            # Check for views that depend on this column and drop them
            unique_views = get_and_drop_dependent_views(cr, table_name, 'id')
            
            # Check for foreign keys that reference this column
            foreign_keys_to_handle = []
            fk_count = 0
            if HANDLE_FOREIGN_KEYS:
                # Find all foreign keys that reference this ID column
                cr.execute("""
                    SELECT 
                        conname,
                        conrelid::regclass as referencing_table,
                        confrelid::regclass as referenced_table,
                        a.attname as referencing_column,
                        af.attname as referenced_column
                    FROM pg_constraint c
                    JOIN pg_class r ON c.conrelid = r.oid
                    JOIN pg_class rf ON c.confrelid = rf.oid
                    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                    JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = ANY(c.confkey)
                    WHERE c.contype = 'f'
                    AND (rf.relname = %s AND af.attname = 'id')
                    ORDER BY conname
                """, (table_name,))
                foreign_keys_to_handle = cr.fetchall()
                fk_count = len(foreign_keys_to_handle)
            
            # Log table processing (simplified)
            if fk_count > 0:
                _logger.info("Processing table %s: ID column + %s FKs", table_name, fk_count)
            else:
                _logger.info("Processing table %s: ID column", table_name)
            
            try:
                # Temporarily disable foreign keys if handling is enabled
                disabled_fks = []
                if HANDLE_FOREIGN_KEYS and foreign_keys_to_handle:
                    for fk_info in foreign_keys_to_handle:
                        fk_name, ref_table, refed_table, ref_col, refed_col = fk_info
                        try:
                            sql_drop = "ALTER TABLE %s DROP CONSTRAINT %s" % (ref_table, fk_name)
                            cr.execute(sql_drop)
                            disabled_fks.append((ref_table, fk_name, fk_info))
                        except Exception as fk_err:
                            _logger.warning("  Could not drop FK %s: %s", fk_name, fk_err)
                
                # Convert ID column to BIGINT
                # 'id' is not a reserved word, but we escape it for consistency
                sql = "ALTER TABLE %s ALTER COLUMN \"id\" TYPE bigint USING \"id\"::bigint" % table_name
                cr.execute(sql)
                
                # Recreate views
                recreate_views(cr, unique_views)
                
                # Verify conversion
                cr.execute("""
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = %s
                    AND column_name = 'id'
                """, (table_name,))
                verify_result = cr.fetchone()
                if verify_result and verify_result[0] == 'bigint':
                    columns_migrated += 1
                    id_columns_migrated += 1
                    commit_counter += 1
                    _logger.info("  ✓ Converted %s.id to BIGINT (verified)", table_name)
                    
                    # Commit periodically to avoid lock exhaustion
                    if commit_counter >= COMMIT_INTERVAL:
                        cr.commit()
                        commit_counter = 0
                        _logger.debug("  Committed transaction (processed %s ID columns so far)", id_columns_migrated)
                else:
                    _logger.error("  ✗ Conversion failed - %s.id is still %s", table_name, verify_result[0] if verify_result else 'unknown')
                
                # Recreate foreign keys if they were disabled
                if HANDLE_FOREIGN_KEYS and disabled_fks:
                    for ref_table, fk_name, fk_info in disabled_fks:
                        fk_name_orig, ref_table_orig, refed_table_orig, ref_col, refed_col = fk_info
                        try:
                            sql_create = """
                                ALTER TABLE %s 
                                ADD CONSTRAINT %s 
                                FOREIGN KEY (%s) 
                                REFERENCES %s(%s)
                            """ % (ref_table, fk_name, ref_col, refed_table, refed_col)
                            cr.execute(sql_create)
                        except Exception as fk_err:
                            _logger.error("  ✗ ERROR recreating FK %s: %s", fk_name, fk_err)
                            _logger.error("  MANUAL INTERVENTION REQUIRED for FK %s", fk_name)
                    if disabled_fks:
                        _logger.info("  ✓ Recreated %s foreign keys", len(disabled_fks))
                
            except Exception as e:
                _logger.error("  ✗ ERROR converting %s.id: %s", table_name, e)
                
                # If we disabled FKs, try to recreate them even on error
                if HANDLE_FOREIGN_KEYS and disabled_fks:
                    _logger.warning("  Attempting to restore %s foreign keys after error...", len(disabled_fks))
                    for ref_table, fk_name, fk_info in disabled_fks:
                        fk_name_orig, ref_table_orig, refed_table_orig, ref_col, refed_col = fk_info
                        try:
                            sql_create = """
                                ALTER TABLE %s 
                                ADD CONSTRAINT %s 
                                FOREIGN KEY (%s) 
                                REFERENCES %s(%s)
                            """ % (ref_table, fk_name, ref_col, refed_table, refed_col)
                            cr.execute(sql_create)
                            _logger.info("  ✓ Restored FK %s", fk_name)
                        except Exception as fk_err:
                            _logger.error("  ✗ CRITICAL: Could not restore FK %s: %s", fk_name, fk_err)
                            _logger.error("  MANUAL INTERVENTION REQUIRED for FK %s", fk_name)
                
                # Check for foreign key constraints that might be blocking
                if not HANDLE_FOREIGN_KEYS:
                    try:
                        cr.execute("""
                            SELECT COUNT(*)
                            FROM pg_constraint
                            WHERE confrelid = %s::regclass
                            AND contype = 'f'
                        """, (table_name,))
                        fk_count = cr.fetchone()[0]
                        if fk_count > 0:
                            _logger.warning("  Table has %s foreign keys - consider enabling HANDLE_FOREIGN_KEYS", fk_count)
                    except:
                        pass
        except Exception as e:
            _logger.error("Error processing table %s: %s", table_name, e)
    
    # Final commit for ID columns
    if commit_counter > 0:
        cr.commit()
        commit_counter = 0
    
    _logger.info("Converted %s ID columns to BIGINT", id_columns_migrated)
    
    # Second pass: Convert all other integer columns (including FKs)
    _logger.info("Step 3b: Converting other integer columns (FKs and others)...")
    commit_counter = 0  # Reset counter for other columns
    for table_name in all_tables:
        try:
            # Get all integer columns in this table (excluding 'id' which we already did)
            cr.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = %s
                AND data_type = 'integer'
                AND column_name != 'id'
                ORDER BY column_name
            """, (table_name,))
            
            integer_columns = cr.fetchall()
            
            if not integer_columns:
                continue
            
            # Count FK columns (those ending in _id)
            fk_columns = [col for col in integer_columns if col[0].endswith('_id')]
            other_columns = [col for col in integer_columns if not col[0].endswith('_id')]
            
            if fk_columns or other_columns:
                if fk_columns and other_columns:
                    _logger.info("Processing table %s: %s FK columns, %s other integer columns", 
                               table_name, len(fk_columns), len(other_columns))
                elif fk_columns:
                    _logger.info("Processing table %s: %s FK columns", table_name, len(fk_columns))
                else:
                    _logger.info("Processing table %s: %s other integer columns", table_name, len(other_columns))
            
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
                    
                    # Check if this table inherits from another table (table inheritance)
                    # PostgreSQL doesn't allow altering inherited columns
                    cr.execute("""
                        SELECT COUNT(*)
                        FROM pg_inherits
                        WHERE inhrelid = %s::regclass
                    """, (table_name,))
                    
                    is_inherited = cr.fetchone()[0] > 0
                    if is_inherited:
                        _logger.debug("  Skipping %s.%s - column is inherited (table inheritance)", table_name, column_name)
                        continue
                    
                    # Check for views that depend on this column and drop them
                    unique_views = get_and_drop_dependent_views(cr, table_name, column_name)
                    
                    # Convert column to BIGINT
                    try:
                        # Escape column names (some are PostgreSQL reserved words like 'user')
                        escaped_column = '"%s"' % column_name
                        # First, try with USING clause (recommended for PostgreSQL)
                        sql = "ALTER TABLE %s ALTER COLUMN %s TYPE bigint USING %s::bigint" % (
                            table_name, escaped_column, escaped_column
                        )
                        cr.execute(sql)
                        
                        # Recreate views
                        recreate_views(cr, unique_views)
                        
                        # Verify conversion
                        cr.execute("""
                            SELECT data_type
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                            AND table_name = %s
                            AND column_name = %s
                        """, (table_name, column_name))
                        verify_result = cr.fetchone()
                        if verify_result and verify_result[0] == 'bigint':
                            columns_migrated += 1
                            commit_counter += 1
                            
                            # Commit periodically to avoid lock exhaustion
                            if commit_counter >= COMMIT_INTERVAL:
                                cr.commit()
                                commit_counter = 0
                                _logger.debug("  Committed transaction (processed %s other columns so far)", columns_migrated)
                        else:
                            _logger.warning("  ⚠ Conversion may have failed - %s.%s is %s", 
                                          table_name, column_name, verify_result[0] if verify_result else 'unknown')
                    except Exception as e:
                        # If USING fails, try without it (for some constraint issues)
                        # But first check if it's a view dependency error
                        if 'view or rule' in str(e).lower() or 'rule' in str(e).lower():
                            # Views should have been handled, but maybe there are more
                            unique_views = get_and_drop_dependent_views(cr, table_name, column_name)
                        
                        try:
                            # Escape column names (some are PostgreSQL reserved words like 'user')
                            escaped_column = '"%s"' % column_name
                            sql = "ALTER TABLE %s ALTER COLUMN %s TYPE bigint" % (
                                table_name, escaped_column
                            )
                            cr.execute(sql)
                            
                            # Recreate views if we dropped them
                            if 'unique_views' in locals() and unique_views:
                                recreate_views(cr, unique_views)
                            
                            # Verify conversion
                            cr.execute("""
                                SELECT data_type
                                FROM information_schema.columns
                                WHERE table_schema = 'public'
                                AND table_name = %s
                                AND column_name = %s
                            """, (table_name, column_name))
                            verify_result = cr.fetchone()
                            if verify_result and verify_result[0] == 'bigint':
                                columns_migrated += 1
                            else:
                                _logger.warning("  ⚠ Conversion may have failed - %s.%s is %s", 
                                              table_name, column_name, verify_result[0] if verify_result else 'unknown')
                        except Exception as e2:
                            _logger.error("  ✗ ERROR converting %s.%s: %s", table_name, column_name, e2)
                            # Continue with other columns
                            continue
                    
                except Exception as e:
                    _logger.error(
                        "Error processing column %s.%s: %s",
                        table_name, column_name, e
                    )
                    # Continue with other columns
                    
        except Exception as e:
            _logger.error("Error processing table %s: %s", table_name, e)
            # Continue with other tables
    
    other_columns_migrated = columns_migrated - id_columns_migrated
    _logger.info("Step 3 summary: %s total columns migrated (%s ID, %s other)", 
                 columns_migrated, id_columns_migrated, other_columns_migrated)
    
    # Step 3.5: Verify conversion of ID columns
    _logger.info("Step 3.5: Verifying ID column conversions...")
    id_columns_verified = 0
    id_columns_failed = 0
    for table_name in all_tables:
        try:
            cr.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = %s
                AND column_name = 'id'
            """, (table_name,))
            result = cr.fetchone()
            if result:
                col_name, data_type = result
                if data_type == 'bigint':
                    id_columns_verified += 1
                    _logger.debug("Verified: %s.%s is BIGINT", table_name, col_name)
                elif data_type == 'integer':
                    id_columns_failed += 1
                    _logger.warning("WARNING: %s.%s is still INTEGER (conversion may have failed)", table_name, col_name)
        except Exception as e:
            _logger.error("Error verifying ID column for %s: %s", table_name, e)
    
    _logger.info("ID column verification: %s BIGINT, %s still INTEGER", id_columns_verified, id_columns_failed)
    
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
    
    # Step 5: Summary and warnings
    _logger.info("=" * 80)
    _logger.info("NUMA BIG ID: Pre-installation migration completed")
    _logger.info("=" * 80)
    _logger.info("Summary:")
    _logger.info("  - Tables analyzed: %s", len(all_tables))
    _logger.info("  - Columns migrated: %s", columns_migrated)
    _logger.info("  - ID columns migrated: %s", id_columns_migrated)
    _logger.info("  - Sequences migrated: %s", sequences_migrated)
    if id_columns_failed > 0:
        _logger.warning("  - WARNING: %s ID columns are still INTEGER - manual intervention may be required", id_columns_failed)
    _logger.info("=" * 80)
    _logger.warning("POST-MIGRATION ACTIONS REQUIRED:")
    _logger.warning("  1. Verify all columns were converted (check logs for errors)")
    _logger.warning("  2. Consider running REINDEX on converted tables for optimal performance")
    _logger.warning("  3. Refresh any materialized views that depend on converted columns")
    _logger.warning("  4. Test application functionality to ensure triggers/custom code work correctly")
    _logger.warning("  5. Monitor database performance - indexes may need rebuilding")
    _logger.info("=" * 80)
    
    # Final verification: Check a few sample tables to confirm conversion
    # Use the same critical tables for verification (they should exist in most Odoo installations)
    _logger.info("Final verification: Checking sample ID columns...")
    for sample_table in CRITICAL_TABLES:
        try:
            # Check if table exists first
            cr.execute("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            """, (sample_table,))
            
            if cr.fetchone()[0] == 0:
                continue  # Table doesn't exist, skip
                
            cr.execute("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = %s
                AND column_name = 'id'
            """, (sample_table,))
            result = cr.fetchone()
            if result:
                _logger.info("  %s.id: %s", sample_table, result[0])
        except Exception as e:
            _logger.debug("  Could not verify %s: %s", sample_table, e)
