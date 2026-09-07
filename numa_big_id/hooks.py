# -*- coding: utf-8 -*-
"""
Widen every 32-bit integer column in the database to 64-bit.

Odoo stores ids and foreign keys as `int4`, which runs out at 2,147,483,647. That ceiling
is not reached by counting records: numa_poly's renumbering allocates every replacement id
*above the global maximum* and never reuses what it frees, so the id space is spent
monotonically. On `int8` the question stops existing.

## The shape of the operation

This is a maintenance-window job: production stopped, no concurrent users, migrate, verify,
open on Monday. Three consequences follow, and the previous version got each of them wrong.

**It commits as it goes, and that is correct.** `ALTER TABLE ... TYPE bigint` rewrites the
table and takes an ACCESS EXCLUSIVE lock on it *and on every table holding a foreign key
into it*. Holding all of that across ~800 tables does not exhaust client memory — it
exhausts PostgreSQL's lock table, and the migration dies with `out of shared memory`
somewhere around `res_users`, which is exactly what it did. Committing after each table
bounds the locks to one table's dependents.

**Committing as it goes makes it non-atomic, so it has to be resumable.** Every step asks
the catalog what still needs doing, so a re-run continues instead of repeating, and an
interrupted run leaves a database that is half wide and wholly consistent.

**A failure must not take its neighbours with it.** Each table is wrapped in a savepoint.
Without one, the first error aborts the transaction and every statement until the next
commit fails too — silently, since the loop catches and continues. That is how a previous
run reported one error and left 190 of 795 id columns still `int4`.

## What it will not do

Materialised views are not touched. Custom triggers and stored procedures referring to the
column types are not inspected. Both are reported, not fixed.
"""

import logging
import os

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Above this many rows in any of the tables below, the migration refuses to start unless
# it is told explicitly to go ahead. It is not a technical limit — it is the line past
# which "install a module" stops being an honest description of what is about to happen.
MAX_SAFE_ROWS = 500_000
CONFIRM_PARAM = 'numa_big_id.confirm_large_migration'
CONFIRM_ENV = 'NUMA_BIG_ID_CONFIRM'

SIZE_PROBE_TABLES = [
    'mail_message', 'mail_tracking_value', 'ir_attachment', 'ir_model_data',
    'account_move_line', 'stock_move', 'stock_move_line', 'res_partner', 'res_users',
]


# --------------------------------------------------------------------------------------
# Catalog queries — every one of them answers "what is still to do", so the whole
# operation is resumable by construction.
# --------------------------------------------------------------------------------------

def _pending_columns(cr):
    """``{table: [column, ...]}`` for every int4 column left in the public schema.

    *Inherited columns* are excluded, not inherited tables. Odoo's action models really do
    use PostgreSQL table inheritance — `ir_act_server`, `ir_act_window` and three others
    inherit from `ir_actions` — and skipping those tables wholesale left their own columns
    behind: `ir_act_server.crud_model_id` stayed int4 pointing at an int8 `ir_model.id`,
    which is precisely the mismatch this module exists to prevent. Only a column with
    `attinhcount > 0` may not be altered on the child, and altering the parent carries it.
    """
    cr.execute("""
        SELECT c.table_name, c.column_name
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
           AND t.table_type = 'BASE TABLE'
         WHERE c.table_schema = 'public'
           AND c.data_type = 'integer'
           AND NOT EXISTS (
                 SELECT 1 FROM pg_attribute a
                  WHERE a.attrelid = to_regclass('public.' || quote_ident(c.table_name))
                    AND a.attname = c.column_name
                    AND a.attinhcount > 0)
         ORDER BY c.table_name, c.ordinal_position
    """)
    pending = {}
    for table, column in cr.fetchall():
        pending.setdefault(table, []).append(column)
    return pending


def _pending_sequences(cr):
    cr.execute("""
        SELECT sequence_name FROM information_schema.sequences
         WHERE sequence_schema = 'public' AND data_type <> 'bigint'
         ORDER BY sequence_name
    """)
    return [row[0] for row in cr.fetchall()]


def _dependent_views(cr, table):
    """Every view that depends on `table`, transitively, with its definition.

    A view built on a view is only reachable by following the chain: dropping the first
    with CASCADE takes the second with it, and a version that did not look would recreate
    one and lose the other without a word.
    """
    cr.execute("""
        WITH RECURSIVE deps AS (
            SELECT v.oid
              FROM pg_depend d
              JOIN pg_rewrite r ON r.oid = d.objid
              JOIN pg_class v ON v.oid = r.ev_class AND v.relkind = 'v'
             WHERE d.refobjid = to_regclass(%s)
               AND v.oid <> d.refobjid
            UNION
            SELECT v.oid
              FROM deps
              JOIN pg_depend d ON d.refobjid = deps.oid
              JOIN pg_rewrite r ON r.oid = d.objid
              JOIN pg_class v ON v.oid = r.ev_class AND v.relkind = 'v'
             WHERE v.oid <> deps.oid
        )
        SELECT n.nspname, c.relname, pg_get_viewdef(c.oid, true)
          FROM deps JOIN pg_class c ON c.oid = deps.oid
          JOIN pg_namespace n ON n.oid = c.relnamespace
    """, ('public.' + table,))
    return cr.fetchall()


def _recreate_views(cr, views):
    """Recreate dropped views, retrying until no more can be built.

    Their creation order is their dependency order and the catalog does not hand it over,
    so this converges on it: each pass creates whatever now has its inputs.
    """
    remaining = list(views)
    while remaining:
        progressed = []
        for schema, name, definition in remaining:
            cr.execute("SAVEPOINT numa_big_id_view")
            try:
                cr.execute('CREATE OR REPLACE VIEW "%s"."%s" AS %s' % (schema, name, definition))
                cr.execute("RELEASE SAVEPOINT numa_big_id_view")
                progressed.append((schema, name, definition))
            except Exception:
                cr.execute("ROLLBACK TO SAVEPOINT numa_big_id_view")
        if not progressed:
            for schema, name, _definition in remaining:
                _logger.error("[big_id] could not recreate view %s.%s — recreate it by hand",
                              schema, name)
            return False
        remaining = [v for v in remaining if v not in progressed]
    return True


# --------------------------------------------------------------------------------------
# The migration
# --------------------------------------------------------------------------------------

FK_BACKUP_TABLE = 'numa_big_id_dropped_fk'


def _ensure_fk_backup(cr):
    """A table holding the foreign keys the migration had to take down.

    It lives in the database, not in memory, because the window between dropping a
    constraint and putting it back is the one moment this operation can lose something
    that is not recoverable from the catalog. If the process dies there, the definitions
    are still on disk and the next run restores them before doing anything else.
    """
    cr.execute("""
        CREATE TABLE IF NOT EXISTS %s (
            child_table text NOT NULL,
            constraint_name text NOT NULL,
            definition text NOT NULL,
            PRIMARY KEY (child_table, constraint_name))
    """ % FK_BACKUP_TABLE)


def _restore_dropped_fks(cr):
    """Put back every constraint the backup table still remembers."""
    _ensure_fk_backup(cr)
    cr.execute("SELECT child_table, constraint_name, definition FROM %s" % FK_BACKUP_TABLE)
    pending = cr.fetchall()
    if not pending:
        return 0
    _logger.info("[big_id] restoring %s foreign key(s) from a previous run", len(pending))
    restored = 0
    for child, name, definition in pending:
        cr.execute("SAVEPOINT numa_big_id_fk")
        try:
            cr.execute('ALTER TABLE %s ADD CONSTRAINT "%s" %s' % (child, name, definition))
            cr.execute("RELEASE SAVEPOINT numa_big_id_fk")
            cr.execute("DELETE FROM %s WHERE child_table = %%s AND constraint_name = %%s"
                       % FK_BACKUP_TABLE, (child, name))
            restored += 1
            if restored % 200 == 0:
                cr.commit()
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT numa_big_id_fk")
            if 'already exists' in str(exc):
                # It was never dropped, or a previous run put it back.
                cr.execute("DELETE FROM %s WHERE child_table = %%s AND constraint_name = %%s"
                           % FK_BACKUP_TABLE, (child, name))
            else:
                _logger.error("[big_id] could not restore %s on %s: %s", name, child, exc)
    cr.commit()
    return restored


def _widen_detaching_fks(cr, table, columns):
    """Widen a table whose incoming foreign keys are too many to lock at once.

    `ALTER COLUMN id TYPE` revalidates every foreign key pointing at the column, which
    means locking every table that holds one. `res_users` is referenced by `create_uid`
    and `write_uid` on essentially every table in the database — some sixteen hundred
    constraints — and PostgreSQL gives up with `out of shared memory` before it starts.

    So the constraints come off first, in their own transaction, with their definitions
    written to disk; the column is widened alone; and they go back on. Raising
    `max_locks_per_transaction` avoids all of this and is the better answer when a DBA is
    at the keyboard, but it needs a restart and this does not.

    Views come down here too. The normal path drops them inside a savepoint, so rolling
    that back brings them straight back and the retry meets `cannot alter type of a column
    used by a view or rule` instead of the lock error it was written for.

    Everything that comes down goes back up in a `finally`: the alter is the step allowed
    to fail, and it must not be able to leave the database without its foreign keys.
    """
    _ensure_fk_backup(cr)
    views = _dependent_views(cr, table)
    for schema, name, _definition in views:
        cr.execute('DROP VIEW IF EXISTS "%s"."%s" CASCADE' % (schema, name))

    cr.execute("""
        SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
          FROM pg_constraint c
         WHERE c.contype = 'f' AND c.confrelid = to_regclass(%s)
    """, ('public.' + table,))
    fks = cr.fetchall()
    _logger.warning("[big_id] %s has %s incoming foreign key(s); detaching them to widen it",
                    table, len(fks))
    for child, name, definition in fks:
        cr.execute("INSERT INTO %s (child_table, constraint_name, definition) "
                   "VALUES (%%s, %%s, %%s) ON CONFLICT DO NOTHING" % FK_BACKUP_TABLE,
                   (child, name, definition))
    cr.commit()

    try:
        for index, (child, name, _definition) in enumerate(fks, start=1):
            cr.execute('ALTER TABLE %s DROP CONSTRAINT IF EXISTS "%s"' % (child, name))
            if index % 200 == 0:
                cr.commit()
        cr.commit()

        alters = ', '.join('ALTER COLUMN "%s" TYPE bigint' % c for c in columns)
        cr.execute('ALTER TABLE "%s" %s' % (table, alters))
        cr.commit()
    finally:
        _recreate_views(cr, views)
        cr.commit()
        restored = _restore_dropped_fks(cr)
        _logger.info("[big_id] %s: %s foreign key(s) back in place", table, restored)


def migrate_to_bigint(cr, dry_run=False):
    """Widen every int4 column in the public schema. Resumable; safe to re-run.

    :return: ``{'tables': n, 'columns': n, 'sequences': n, 'failed': {table: reason}}``
    """
    if not dry_run:
        _restore_dropped_fks(cr)
    pending = _pending_columns(cr)
    report = {'tables': 0, 'columns': 0, 'sequences': 0, 'failed': {}}
    if dry_run:
        report['tables'] = len(pending)
        report['columns'] = sum(len(c) for c in pending.values())
        report['sequences'] = len(_pending_sequences(cr))
        return report

    total = len(pending)
    _logger.info("[big_id] %s table(s) with %s int4 column(s) to widen",
                 total, sum(len(c) for c in pending.values()))

    for index, (table, columns) in enumerate(sorted(pending.items()), start=1):
        cr.execute("SAVEPOINT numa_big_id_table")
        try:
            views = _dependent_views(cr, table)
            for schema, name, _definition in views:
                cr.execute('DROP VIEW IF EXISTS "%s"."%s" CASCADE' % (schema, name))

            # Every column of the table in ONE statement: `ALTER COLUMN ... TYPE` rewrites
            # the whole table, so doing them one at a time rewrites it once per column —
            # twenty rewrites for a table with twenty integer columns.
            alters = ', '.join('ALTER COLUMN "%s" TYPE bigint' % c for c in columns)
            cr.execute('ALTER TABLE "%s" %s' % (table, alters))

            _recreate_views(cr, views)
            cr.execute("RELEASE SAVEPOINT numa_big_id_table")
            # Per table, not per batch: the lock this took covers the table and everything
            # holding a foreign key into it, and res_users alone brings hundreds.
            cr.commit()
            report['tables'] += 1
            report['columns'] += len(columns)
            if index % 50 == 0 or index == total:
                _logger.info("[big_id] %s/%s tables", index, total)
        except Exception as exc:
            # Roll back to the savepoint so the cursor is usable: without it the
            # transaction stays aborted and every table after this one fails too.
            cr.execute("ROLLBACK TO SAVEPOINT numa_big_id_table")
            cr.commit()
            reason = str(exc).strip().splitlines()[0]
            if 'out of shared memory' in reason or 'max_locks_per_transaction' in reason:
                try:
                    _widen_detaching_fks(cr, table, columns)
                    report['tables'] += 1
                    report['columns'] += len(columns)
                    continue
                except Exception as retry_exc:
                    cr.rollback()
                    reason = str(retry_exc).strip().splitlines()[0]
            report['failed'][table] = reason
            _logger.error("[big_id] %s: %s", table, reason)

    for sequence in _pending_sequences(cr):
        cr.execute("SAVEPOINT numa_big_id_seq")
        try:
            cr.execute('ALTER SEQUENCE "%s" AS bigint' % sequence)
            cr.execute("RELEASE SAVEPOINT numa_big_id_seq")
            report['sequences'] += 1
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT numa_big_id_seq")
            _logger.error("[big_id] sequence %s: %s", sequence, exc)
    cr.commit()

    _logger.info("[big_id] widened %s column(s) across %s table(s), %s sequence(s)",
                 report['columns'], report['tables'], report['sequences'])
    return report


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------

def verify_bigint(cr):
    """What is still 32-bit, and where a foreign key now spans both widths.

    The mismatches are the reason this exists. A parent whose `id` is `int8` and a child
    whose foreign key is still `int4` does not fail today; it fails the day that sequence
    passes 2,147,483,647, on that table alone, in production. A migration that leaves them
    behind is worse than one that never ran, because the failure stops being global and
    predictable and becomes local and surprising.

    :return: ``{'int4_ids': [...], 'int4_columns': n, 'fk_mismatches': [...],
                'int4_sequences': [...], 'clean': bool}``
    """
    cr.execute("""
        SELECT table_name FROM information_schema.columns
         WHERE table_schema = 'public' AND column_name = 'id' AND data_type = 'integer'
         ORDER BY table_name
    """)
    int4_ids = [row[0] for row in cr.fetchall()]

    cr.execute("""
        SELECT count(*) FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
           AND t.table_type = 'BASE TABLE'
         WHERE c.table_schema = 'public' AND c.data_type = 'integer'
    """)
    int4_columns = cr.fetchone()[0]

    cr.execute("""
        SELECT c.conrelid::regclass::text, a.attname, ta.typname,
               c.confrelid::regclass::text, tr.typname
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
          JOIN pg_type ta ON ta.oid = a.atttypid
          JOIN pg_attribute r ON r.attrelid = c.confrelid AND r.attnum = c.confkey[1]
          JOIN pg_type tr ON tr.oid = r.atttypid
         WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1
           AND ta.typname IS DISTINCT FROM tr.typname
           AND ta.typname IN ('int4', 'int8') AND tr.typname IN ('int4', 'int8')
         ORDER BY 1, 2
    """)
    mismatches = cr.fetchall()

    cr.execute("SELECT to_regclass(%s)", ('public.' + FK_BACKUP_TABLE,))
    detached = []
    if cr.fetchone()[0]:
        cr.execute("SELECT child_table, constraint_name FROM %s" % FK_BACKUP_TABLE)
        detached = cr.fetchall()

    result = {
        'int4_ids': int4_ids,
        'int4_columns': int4_columns,
        'fk_mismatches': mismatches,
        'int4_sequences': _pending_sequences(cr),
        'detached_fks': detached,
    }
    result['clean'] = not (int4_ids or mismatches or result['int4_sequences'] or detached)
    return result


def log_verification(cr):
    """Write the gate's answer to the log and say whether it passed."""
    result = verify_bigint(cr)
    if result['clean']:
        _logger.info("[big_id] verification passed: every id, foreign key and sequence "
                     "is 64-bit (%s int4 column(s) left, none of them identity)",
                     result['int4_columns'])
        return result
    if result['int4_ids']:
        _logger.error("[big_id] %s id column(s) still int4: %s",
                      len(result['int4_ids']), ', '.join(result['int4_ids'][:20]))
    for child, col, ctype, parent, ptype in result['fk_mismatches'][:20]:
        _logger.error("[big_id] foreign key %s.%s (%s) -> %s.id (%s)",
                      child, col, ctype, parent, ptype)
    if len(result['fk_mismatches']) > 20:
        _logger.error("[big_id] ... and %s more foreign keys spanning both widths",
                      len(result['fk_mismatches']) - 20)
    if result['int4_sequences']:
        _logger.error("[big_id] %s sequence(s) still int4: %s",
                      len(result['int4_sequences']), ', '.join(result['int4_sequences'][:20]))
    if result['detached_fks']:
        _logger.error("[big_id] %s foreign key(s) are still detached; their definitions "
                      "are in %s and the next run puts them back",
                      len(result['detached_fks']), FK_BACKUP_TABLE)
    return result


# --------------------------------------------------------------------------------------
# Size check and entry point
# --------------------------------------------------------------------------------------

def _confirmed(cr):
    if os.environ.get(CONFIRM_ENV):
        return True
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (CONFIRM_PARAM,))
    row = cr.fetchone()
    return bool(row) and str(row[0]).strip().lower() not in ('', '0', 'false', 'no')


def _check_size(cr):
    """Report what the migration is about to rewrite, and stop if nobody said to.

    Not a technical limit. Past this size the operation is hours of table rewrites needing
    up to twice the disk, and it deserves to be a decision somebody made rather than the
    side effect of ticking a module in the interface.
    """
    biggest = []
    for table in SIZE_PROBE_TABLES:
        cr.execute("SELECT to_regclass(%s)", ('public.' + table,))
        if not cr.fetchone()[0]:
            continue
        cr.execute('SELECT count(*) FROM "%s"' % table)
        biggest.append((cr.fetchone()[0], table))
    biggest.sort(reverse=True)
    for rows, table in biggest[:5]:
        _logger.info("[big_id] %s: %s rows", table, rows)

    if biggest and biggest[0][0] > MAX_SAFE_ROWS and not _confirmed(cr):
        rows, table = biggest[0]
        raise UserError(
            "numa_big_id rewrites every table in this database to widen its integer "
            "columns.\n\n"
            "%s holds %s rows, over the %s at which this stops being a routine install: "
            "expect hours of ACCESS EXCLUSIVE locks and up to twice the disk while it "
            "runs. Stop the service, take a backup you have restored at least once, and "
            "then confirm deliberately:\n\n"
            "    INSERT INTO ir_config_parameter (key, value) VALUES ('%s', '1');\n\n"
            "or set %s=1 in the environment. The migration commits table by table and is "
            "resumable, so an interrupted run is continued by installing again."
            % (table, rows, MAX_SAFE_ROWS, CONFIRM_PARAM, CONFIRM_ENV))


def pre_init_hook(env):
    """Widen the database before this module's own tables are created.

    Runs before the module is loaded, which is the only moment the schema is still the
    one every other module built. Raises if the result does not pass the gate: a module
    that reports `installed` over a half-widened database is the failure this whole file
    is written against.
    """
    cr = env.cr
    _logger.info("[big_id] widening the database to 64-bit integers")
    _check_size(cr)

    cr.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
               "WHERE n.nspname = 'public' AND c.relkind = 'm'")
    materialized = cr.fetchone()[0]
    if materialized:
        _logger.warning("[big_id] %s materialised view(s) are not touched; refresh them "
                        "after the migration", materialized)

    migrate_to_bigint(cr)
    result = log_verification(cr)
    if not result['clean']:
        raise UserError(
            "The conversion to 64-bit did not complete.\n\n"
            "%s id column(s), %s foreign key(s) spanning both widths and %s sequence(s) "
            "are still 32-bit; the log lists them. The database is consistent — the "
            "migration commits per table — so fix what the log names and install again "
            "to continue where it stopped.\n\n"
            "Leaving it half done is the one outcome worth refusing: a foreign key whose "
            "child is int4 and whose parent is int8 works until that table's ids pass "
            "2,147,483,647, and then fails alone, in production."
            % (len(result['int4_ids']), len(result['fk_mismatches']),
               len(result['int4_sequences'])))
    _logger.info("[big_id] done")
