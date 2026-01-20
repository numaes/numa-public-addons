# Numa Big ID

## Description

This module is a critical dependency of `numa_poly`. Odoo uses `int4` (Integer) by default for IDs and foreign keys, which limits records to 2.147 billion. `numa_poly` unifies sequences, which will quickly exhaust this limit.

The objective of `numa_big_id` is to convert **all integer arithmetic in the database to 64-bit (`int8` / `BIGINT`)** to guarantee infinite scalability.

## Features

- **Pre-installation Migration**: Automatically converts all `integer` columns to `BIGINT` during installation
- **Safety Check**: Verifies that critical tables do not exceed 500,000 records before migration
- **ORM Monkey Patch**: Forces all `Integer` fields to map to `BIGINT` in PostgreSQL
- **Sequence Conversion**: Converts all sequences to `BIGINT`
- **View Handling**: Automatically detects and recreates views that depend on converted columns
- **Table Inheritance Handling**: Skips inherited columns (cannot be altered directly)
- **Reserved Words Handling**: Properly escapes column names that are PostgreSQL reserved words
- **Periodic Commits**: Performs commits every 50 conversions to avoid lock exhaustion

## Architecture

### Pre-installation Hook (`hooks.py`)

The `pre_init_hook` runs during module installation and performs:

1. **Safety Check**: Verifies that common critical tables do not exceed `MAX_SAFE_ROWS` (500,000 by default)
2. **ID Column Migration**: Converts all `id` columns of type `integer` to `bigint`
3. **Other Columns Migration**: Converts all other `integer` columns (FKs, numeric fields, etc.)
4. **Sequence Migration**: Converts all sequences to `bigint`
5. **Final Verification**: Verifies that conversions were successful

**Hook Features:**
- Processes **ALL** tables in the `public` schema, without depending on specific modules
- Automatically handles dependent views (temporarily drops and recreates them)
- Skips tables with inheritance (inherited columns are converted in the parent table)
- Escapes column names that are PostgreSQL reserved words
- Performs periodic commits to avoid lock exhaustion

### ORM Monkey Patch (`models/big_int_patch.py`)

The patch is applied when the module loads and modifies:

- `fields.Integer.column_type`: Returns `('int8', 'bigint')` instead of `('int4', 'int4')`
- `fields.Many2one.column_type`: Applies the same patch for foreign keys
- `fields.Many2many._update_relation_table`: Ensures that relation tables use `BIGINT`

**Compatibility:**
- Compatible with Odoo 18 (uses `lazy_property` correctly)
- Correctly handles subscript access (`field.column_type[1]`)
- Does not interfere with other modules

## Installation

**IMPORTANT**: This module must be installed **BEFORE** any other module that uses polymorphic models (such as `numa_poly`).

1. Add the module to the addons list
2. Update the module list
3. Install `numa_big_id` first
4. Then install other modules that depend on it

**Note**: The `pre_init_hook` only runs during initial installation. If the module is already installed and you need to run the migration, you must uninstall and reinstall it.

## Configuration

The module has two configurable constants in `hooks.py`:

- `MAX_SAFE_ROWS = 500000`: Record limit in critical tables before aborting migration
- `HANDLE_FOREIGN_KEYS = False`: If `True`, drops and recreates foreign keys during `id` column conversion (can be very slow on medium/large databases)

## Limitations and Risks

### Technical Limitations

- **Irreversible Migration**: The migration to BIGINT cannot be automatically reverted
- **Large Databases**: If any critical table has more than 500,000 records, installation will be aborted and manual migration by a DBA will be required
- **Compatibility**: Compatible with Odoo 18 (tested), should work on 16 and 17
- **Tables with Inheritance**: Inherited columns are skipped (converted in the parent table)
- **Complex Views**: Some very complex views may require manual recreation if automatic recreation fails

### Critical Risks in Large Databases

⚠️ **WARNING**: This module is designed for relatively small databases (<500k records in critical tables). For large databases, use manual migration by a DBA.

#### 1. Non-Atomic Migration
- **Problem**: Intermediate commits (every 50 tables) make the migration NOT atomic
- **Risk**: If there is an interruption (power failure, crash, etc.), the database will be left in a partially migrated state
- **Impact**: NO automatic rollback - requires manual intervention to restore from backup or complete the migration
- **Mitigation**: 
  - Perform full backup before installing
  - Have a rollback plan (restore from backup)
  - Monitor the process and have sufficient maintenance window

#### 2. Disk Space
- **Problem**: PostgreSQL creates new files before deleting old ones during `ALTER TABLE`
- **Risk**: May require up to **2x the current database size** temporarily
- **Impact**: If there is insufficient space, the migration will fail and leave the database in an inconsistent state
- **Mitigation**: 
  - Verify available space before migrating
  - Have at least 2x the database size available
  - Monitor space during migration

#### 3. Prolonged Locks
- **Problem**: `ALTER TABLE ... ALTER COLUMN TYPE` acquires exclusive locks on tables
- **Risk**: Blocks reads and writes during conversion (can be minutes or hours on large tables)
- **Impact**: Application inaccessible during migration of critical tables
- **Mitigation**:
  - Execute during maintenance window
  - Consider planned downtime
  - For large databases, use online migration techniques (requires DBA)

#### 4. Indexes
- **Problem**: Indexes on converted columns may become inconsistent or need recreation
- **Risk**: Degraded performance until indexes are rebuilt
- **Impact**: Slow queries, possible general performance degradation
- **Mitigation**:
  - Plan `REINDEX` after migration
  - Monitor post-migration performance
  - Consider manually recreating critical indexes

#### 5. Materialized Views
- **Problem**: Materialized views are not handled (only regular views)
- **Risk**: Materialized views may become inconsistent or require manual refresh
- **Impact**: Incorrect data in reports that use materialized views
- **Mitigation**:
  - Identify materialized views before migrating
  - Manually refresh after migration
  - Verify data integrity

#### 6. Custom Triggers
- **Problem**: Triggers that depend on specific types may fail
- **Risk**: Triggers may not execute correctly or cause errors
- **Impact**: Custom business logic may fail
- **Mitigation**:
  - Audit triggers before migrating
  - Test in development environment first
  - Have rollback plan for critical triggers

#### 7. Replication
- **Problem**: If there is streaming replication, massive changes can cause lag or failures
- **Risk**: Replication may become desynchronized or fail
- **Impact**: Standby servers may become inconsistent
- **Mitigation**:
  - Pause replication during migration (if possible)
  - Monitor replication lag
  - Have resynchronization plan

#### 8. Execution Time
- **Problem**: On large databases, migration can take hours
- **Risk**: Insufficient maintenance window
- **Impact**: Incomplete migration if interrupted
- **Mitigation**:
  - Estimate time based on database size
  - Have sufficient maintenance window (hours, not minutes)
  - Continuously monitor progress

#### 9. Foreign Keys
- **Problem**: FK handling is disabled by default (`HANDLE_FOREIGN_KEYS = False`)
- **Risk**: `id` column conversion may fail if there are blocking FKs
- **Impact**: Some tables may not be migrated
- **Mitigation**:
  - Enable `HANDLE_FOREIGN_KEYS = True` only if database is small
  - For large databases, migrate FKs manually before converting columns
  - Verify that all columns were migrated correctly

### Recommendations for Large Databases

1. **DO NOT use automatic migration** if:
   - Database has >500k records in critical tables
   - It is a critical production system
   - There is no sufficient maintenance window (hours)
   - There is no recent backup and rollback plan

2. **Use manual migration by DBA** that includes:
   - Full backup before starting
   - Batch migration (table by table)
   - Integrity verification after each batch
   - Detailed rollback plan
   - Continuous monitoring of space, locks, and performance
   - Index recreation after migration
   - Materialized view refresh
   - Trigger validation

## Usage

Once installed, the module:

1. Automatically migrates all existing `integer` columns to `BIGINT`
2. Patches the ORM so all new `Integer` fields are created as `BIGINT`
3. Ensures sequences use `BIGINT`

No additional configuration is required after installation.

## Generalization

This module is completely generalized and does not depend on specific modules:

- **Processes all tables**: No hardcoding of specific table names (except for safety check)
- **Generic safety check**: Tables in `CRITICAL_TABLES` are only for estimating database size
- **No module dependencies**: Works with any combination of installed modules
- **Automatic handling**: Automatically detects and handles views, inheritance, reserved words, etc.

## Troubleshooting

### Error: "The database is too large for safe automatic migration"

If you receive this error, it means that some critical table has more than 500,000 records. Options:

1. **Adjust the limit**: Modify `MAX_SAFE_ROWS` in `hooks.py` if you trust that the migration will work
2. **Manual migration**: Contact a DBA to perform manual migration using SQL scripts
3. **Once manual migration is completed**: You can install the module (the hook will detect that columns are already BIGINT and skip them)

### Error: "cannot alter inherited column"

This error indicates that a table uses PostgreSQL table inheritance. The module automatically skips these columns. The parent table should be converted, and children will inherit the `BIGINT` type.

### Error: "cannot alter type of a column used by a view or rule"

This error should not occur, as the module automatically detects and handles views. If it occurs:

1. Check logs to see if there was an error recreating the view
2. Manually recreate the view if necessary
3. Report the case to improve view handling

### Verify that migration was successful

You can verify that columns were converted by executing:

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
AND data_type = 'integer'
ORDER BY table_name, column_name;
```

If the migration was successful, this query should not return results (or only columns that should not be BIGINT, such as inherited columns that will be converted in the parent table).

### Verify sequences

```sql
SELECT sequence_name, data_type
FROM information_schema.sequences
WHERE sequence_schema = 'public'
AND data_type != 'bigint';
```

All sequences should be `bigint` after migration.

## Author

NUMA Extreme Systems

## License

AGPL-3
