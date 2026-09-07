# -*- coding: utf-8 -*-
"""
Numa Big ID: every 32-bit integer column in the database becomes 64-bit.

`hooks` carries the migration and the verification gate; `models` patches the ORM so that
everything created afterwards is 64-bit from the start. The patch is applied at import
time, before any model is defined, which is what makes the two halves agree.
"""

from . import hooks
from . import models

# Odoo looks these up as attributes of the module.
pre_init_hook = hooks.pre_init_hook

# Usable from a shell, so a DBA can migrate and verify without installing anything:
#   from odoo.addons.numa_big_id import migrate_to_bigint, verify_bigint, log_verification
migrate_to_bigint = hooks.migrate_to_bigint
verify_bigint = hooks.verify_bigint
log_verification = hooks.log_verification
