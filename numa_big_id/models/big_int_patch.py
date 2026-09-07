# -*- coding: utf-8 -*-
"""
Make the ORM emit BIGINT wherever it would emit INTEGER.

Odoo declares the SQL type of a field in a plain class attribute, `_column_type`, which
the base `Field.column_type` lazy_property reads. Exactly two classes declare
`('int4', 'int4')` — `Integer` (odoo/fields.py:1530) and `Many2one` (:3231) — so making
every id and every foreign key 64-bit is two assignments.

Two more places do not go through a field at all, and both write the type into a DDL
string:

- `Many2many.update_db` creates the relation table with `INTEGER NOT NULL`
  (odoo/fields.py:5036).
- `sql.create_model_table` creates every model's table with `id SERIAL NOT NULL`
  (odoo/tools/sql.py:268), and `SERIAL` is int4.

The second one is the reason a first attempt at this file looked like it worked: the
many2many tables came out wide, the foreign keys came out wide, and every `id` created
afterwards was still int4 — leaving 970 foreign keys pointing from int8 down to int4,
which is exactly the state this module exists to prevent.

An earlier version of this file replaced `column_type` with a custom descriptor and
reconstructed the original getter through four branches of fallback. It was 291 lines,
and it broke something: `Field.setup` calls `lazy_property.reset_all(self)` precisely
because "column_type might be changed during Field.setup", and that reset only clears
attributes whose class descriptor is a `lazy_property`. A replacement descriptor is not
one, so the cached value of every Integer and Many2one field stopped being invalidated —
including the `company_dependent`/`translate` fields whose column really does become
jsonb during setup. Setting the class attribute leaves the lazy_property intact.
"""

import logging

import odoo
from odoo import fields
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

BIGINT = ('int8', 'int8')

_original_many2many_update_db = fields.Many2many.update_db
_original_create_model_table = odoo.tools.sql.create_model_table


def _many2many_update_db_bigint(self, model, columns):
    """Create a many2many relation table with BIGINT columns.

    The relation table is not built from a field's `column_type`; the type is written
    into the DDL. Creating it here, before delegating, means the table is right the first
    time — the alternative is creating it as INTEGER and altering it afterwards, which
    rewrites a table that may already be large and leaves a window where it is wrong.
    """
    cr = model._cr
    if not odoo.tools.sql.table_exists(cr, self.relation):
        comodel = model.env[self.comodel_name]
        cr.execute(SQL(
            """ CREATE TABLE %(rel)s (%(id1)s BIGINT NOT NULL,
                                      %(id2)s BIGINT NOT NULL,
                                      PRIMARY KEY(%(id1)s, %(id2)s));
                COMMENT ON TABLE %(rel)s IS %(comment)s;
                CREATE INDEX ON %(rel)s (%(id2)s, %(id1)s); """,
            rel=SQL.identifier(self.relation),
            id1=SQL.identifier(self.column1),
            id2=SQL.identifier(self.column2),
            comment=f"RELATION BETWEEN {model._table} AND {comodel._table}",
        ))
        _logger.debug("[big_id] created m2m relation table %s with BIGINT columns",
                      self.relation)
    # The table now exists, so the original takes its "already there" path and only
    # registers the reflection and the foreign keys.
    return _original_many2many_update_db(self, model, columns)


def _create_model_table_bigint(cr, tablename, comment=None, columns=()):
    """Create a model's table and widen its `id` before anything can be inserted.

    `create_model_table` writes `id SERIAL NOT NULL`, and SERIAL is int4. Rather than
    reimplement the statement — which would have to be kept in step with every Odoo
    release — this lets it run and widens the column and its sequence immediately. The
    table is empty at that instant, so the rewrite costs nothing.
    """
    result = _original_create_model_table(cr, tablename, comment=comment, columns=columns)
    cr.execute(SQL("ALTER TABLE %s ALTER COLUMN id TYPE bigint",
                   SQL.identifier(tablename)))
    cr.execute("SELECT pg_get_serial_sequence(%s, 'id')", (tablename,))
    row = cr.fetchone()
    if row and row[0]:
        cr.execute('ALTER SEQUENCE %s AS bigint' % row[0])
    _logger.debug("[big_id] created %s with a 64-bit id", tablename)
    return result


def apply_bigint_patch():
    """Idempotent: safe to call again after a registry reload."""
    if fields.Integer._column_type == BIGINT:
        return
    fields.Integer._column_type = BIGINT
    fields.Many2one._column_type = BIGINT
    fields.Many2many.update_db = _many2many_update_db_bigint
    odoo.tools.sql.create_model_table = _create_model_table_bigint
    _logger.info("[big_id] Integer, Many2one, new model tables and m2m relation tables "
                 "now map to BIGINT")


apply_bigint_patch()
