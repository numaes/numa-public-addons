# -*- coding: utf-8 -*-
import logging

from odoo import models
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    # Required columns that website adds to ir_ui_view with a default the ORM applies
    # but the database does not.
    _numa_db_default_fields = ('visibility',)

    def _auto_init(self):
        """Give each of those columns its field's default at database level.

        An upgrade loads modules in dependency depth order, so a module that does not
        depend on website loads its data before website's model extension is in the
        registry. A view it inserts then omits `visibility`, and the column rejects the
        NULL ("null value in column visibility of relation ir_ui_view"), which aborts
        the whole upgrade. Reproduced on Odoo 20 without any numa module, so it is
        core's; this only moves the default where it is always seen.

        It runs whenever ir.ui.view is initialised (install, or an upgrade of this
        module or of website), and it follows the field's default if Odoo changes it.
        """
        res = super()._auto_init()
        for name in self._numa_db_default_fields:
            field = self._fields.get(name)
            if not field or not field.store or not callable(field.default):
                continue
            value = field.default(self)
            if value in (None, False):
                continue
            self.env.cr.execute(SQL(
                "ALTER TABLE %s ALTER COLUMN %s SET DEFAULT %s",
                SQL.identifier(self._table), SQL.identifier(name), value))
            _logger.debug("ir_ui_view.%s defaults to %r in the database", name, value)
        return res
