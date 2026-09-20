# -*- coding: utf-8 -*-
"""One last sweep once everything is loaded.

Each of this module's two mechanisms has its own blind window:

- ``pre_init_hook`` widens what already exists, and it is the only moment when
  the schema is the one the other modules built. But the ``auto_install``
  modules -``web``, ``auth_totp`` and whatever they drag in- are installed later
  in the same run, and their tables do not exist yet when it runs.
- The ``create_model_table`` patch takes care of new tables, and it was verified
  to do so. But a model with ``_auto = False`` never goes through it: it writes
  its own DDL, and in core that DDL says ``id serial``
  (``res_users.py:1554``), which is ``int4``.

Where the two windows cross is not hypothetical, and it showed on a clean
install: ``auth_totp_device`` -which is ``_auto = False`` and installs late- was
left with a 32-bit ``id``, and the gate reported the module ``installed`` all
the same. A module that says ``installed`` over a half-widened database is
exactly what this module exists to prevent.

``_register_hook`` is the anchor that was missing: Odoo calls it with every
module loaded (``registry.py:577``), which is after the ``auto_install`` ones
and after any hand-written ``init()``.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# A mark on the registry: the sweep runs once per generation, not once per model.
_SWEPT = '_big_id_swept__'


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def _register_hook(self):
        resultado = super()._register_hook()
        registry = self.env.registry
        if registry.__dict__.get(_SWEPT):
            return resultado
        setattr(registry, _SWEPT, True)

        from ..hooks import _pending_columns, migrate_to_bigint, log_verification

        cr = self.env.cr
        pendientes = _pending_columns(cr)
        if not pendientes:
            return resultado

        _logger.info("[big_id] %s table(s) were left at 32 bits after the modules loaded; "
                     "widening them: %s", len(pendientes), ', '.join(sorted(pendientes)))
        migrate_to_bigint(cr)
        resultado_verificacion = log_verification(cr)
        if not resultado_verificacion['clean']:
            # The load is not aborted: by this point the modules are installed
            # and aborting leaves the database in a worse state. It is reported
            # in full detail instead, which is what log_verification just wrote.
            _logger.error("[big_id] the database still has 32-bit columns after the final "
                          "sweep; the log above names them")
        return resultado
