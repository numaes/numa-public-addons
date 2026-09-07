# -*- coding: utf-8 -*-
{
    'name': 'Numa Big ID',
    'version': '18.0.1.0.0',
    'summary': 'Convert all integer IDs and foreign keys to BIGINT (int8) for infinite scalability',
    'description': """
Numa Big ID
===========

Odoo stores ids and foreign keys as `int4`, which runs out at 2,147,483,647. This module
widens every 32-bit integer column in the database to 64-bit, and patches the ORM so that
everything created afterwards is 64-bit from the start.

The ceiling is not reached by counting records. `numa_poly` allocates every replacement id
above the global maximum and never reuses what it frees, so the id space is spent
monotonically: each collision repaired costs ids permanently. On `int8` the question stops
existing.

**This is a maintenance-window operation.** Stop the service, take a backup you have
restored at least once, migrate, verify, reopen. The migration rewrites every table —
`ALTER TABLE ... TYPE bigint` is not a metadata change — taking an ACCESS EXCLUSIVE lock
on each table and on everything holding a foreign key into it.

How it behaves:

- **Commits table by table.** Holding the locks for ~800 tables does not exhaust client
  memory, it exhausts PostgreSQL's lock table and dies with `out of shared memory`.
- **Is resumable.** Every step asks the catalog what is still narrow, so an interrupted
  run is continued by installing again. It commits as it goes, so it is not atomic — which
  is exactly why it must be safe to re-run.
- **Isolates failures.** Each table runs inside a savepoint; one failure does not abort
  the transaction and take its neighbours down silently with it.
- **Refuses to report success while anything is left.** A foreign key whose child is int4
  and whose parent is int8 works until that table's ids pass 2,147,483,647 and then fails
  alone, in production. Half-widened is the one outcome worth refusing.
- **Widens all integer columns**, not only ids and foreign keys: `res_id` columns
  (attachments, messages, external ids) hold ids and carry no constraint that would
  identify them.

Above 500,000 rows in a high-volume table the install stops and asks for a deliberate
confirmation (`numa_big_id.confirm_large_migration` = `1`, or `NUMA_BIG_ID_CONFIRM=1`),
because past that size "install a module" stops being an honest description of it.

Not handled: materialised views (reported, refresh them afterwards) and custom triggers or
stored procedures that name the column types.

Install it on a database that has not been migrated yet, verify with
`numa_big_id.verify_bigint(cr)`, and only then install the rest.
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'AGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'base',
    ],
    'data': [],
    'installable': True,
    'auto_install': False,
    # This module should be installed first, before any polymorphic models
    'sequence': 0,
    # Register pre-installation hook for database migration
    'pre_init_hook': 'pre_init_hook',
}
