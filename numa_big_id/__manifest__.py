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
- Pre-installation hook that migrates all integer columns to BIGINT
- Safety check to prevent migration on databases with >500k records
- Monkey patch of Odoo ORM to force Integer fields to map to BIGINT
- Automatic sequence conversion to BIGINT

**Important:**
- This module must be installed BEFORE any other modules that use polymorphic models
- The migration is irreversible without manual database intervention
- For large databases (>500k records), manual migration by a DBA is required
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
