# -*- coding: utf-8 -*-
{
    'name': 'Numa Big ID',
    'version': '18.0.1.0.0',
    'summary': 'Convert all integer IDs and foreign keys to BIGINT (int8) for infinite scalability',
    'description': """
Numa Big ID
===========

This module is a critical dependency of `numa_poly`. Odoo uses `int4` (Integer) by default
for IDs and foreign keys, which limits records to 2.147 billion. `numa_poly` unifies sequences,
which will quickly exhaust this limit.

This module converts all integer arithmetic in the database to 64-bit (`int8` / `BIGINT`)
to guarantee infinite scalability.

**Features:**
- Pre-installation hook that migrates ALL integer columns to BIGINT (fully generalized)
- Safety check to prevent migration on databases with >500k records in critical tables
- Monkey patch of Odoo ORM to force Integer fields to map to BIGINT
- Automatic sequence conversion to BIGINT
- Automatic handling of dependent views (drop and recreate)
- Automatic handling of table inheritance (skip inherited columns)
- Automatic handling of PostgreSQL reserved words (escape column names)
- Periodic commits to avoid lock exhaustion

**Architecture:**
- Completely generalized - processes ALL tables in the database
- No hardcoded dependencies on specific modules or models
- Works with any combination of installed Odoo modules
- Handles edge cases automatically (views, inheritance, reserved words)

**Important:**
- This module must be installed BEFORE any other modules that use polymorphic models
- The migration is irreversible without manual database intervention
- For large databases (>500k records in critical tables), manual migration by a DBA is required
- The pre_init_hook only runs during initial installation (uninstall/reinstall to re-run)
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
