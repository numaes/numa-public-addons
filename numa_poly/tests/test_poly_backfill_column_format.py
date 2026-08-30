# -*- coding: utf-8 -*-
"""
The backfill writes SQL, so it owes Postgres the column format.

`default_get` answers in the *write* format, which is not what a column takes. The two
agree for scalars and part ways everywhere else, and the first place it showed was a
customer upgrade: a `fields.Json(default={})` on a base model reached a `jsonb` column
as the boolean `false` and killed the whole `-u`.
"""
import psycopg2

from odoo import fields
from odoo.tests import tagged, TransactionCase

from ..models.poly import _poly_sql_param


@tagged('post_install', '-at_install')
class TestPolyBackfillColumnFormat(TransactionCase):
    """What the INSERT parameters have to look like."""

    def setUp(self):
        super().setUp()
        self.env.cr.execute("CREATE TEMP TABLE poly_json_probe (v jsonb)")

    def _insert(self, value):
        self.env.cr.execute("INSERT INTO poly_json_probe (v) VALUES (%s)", (value,))

    # ------------------------------------------------------------------
    def test_01_the_write_format_of_an_empty_json_default_is_false(self):
        """
        The chain that produced the crash, pinned.

        `convert_to_cache({})` is None because `{}` is falsy, `convert_to_record(None)`
        is False, and `default_get` returns that. It is not None, so a filter that only
        drops None lets it through.
        """
        field = fields.Json('Instance Variables', default={})
        cache_value = field.convert_to_cache({}, self.env['ir.poly_base'], validate=False)
        write_value = field.convert_to_write(cache_value, self.env['ir.poly_base'])

        self.assertIs(write_value, False)

    def test_02_postgres_refuses_that_value_for_a_jsonb_column(self):
        """Why the upgrade died rather than storing something wrong quietly."""
        with self.assertRaises(psycopg2.errors.DatatypeMismatch):
            with self.env.cr.savepoint():
                self._insert(False)

    def test_03_the_orm_conversion_is_what_a_jsonb_column_accepts(self):
        """`convert_to_column_insert` is the conversion `create()` itself uses."""
        field = fields.Json('Instance Variables', default={})

        column_value = field.convert_to_column_insert(False, self.env['ir.poly_base'])

        self.assertIsNone(column_value, "An empty Json default means: leave the column alone.")

    def test_04_a_dict_read_off_a_jsonb_column_can_be_put_back(self):
        """
        The mirror problem, on the copy path.

        psycopg2 reads a jsonb column back as a plain dict and has no adapter for one on
        the way in, so copying such a column from a concrete row to its base row fails
        with "can't adapt type 'dict'" unless it is wrapped.
        """
        with self.assertRaises(psycopg2.ProgrammingError):
            with self.env.cr.savepoint():
                self._insert({'count': 1})

        self._insert(_poly_sql_param({'count': 1}))
        self.env.cr.execute("SELECT v FROM poly_json_probe")
        self.assertEqual(self.env.cr.fetchone()[0], {'count': 1})

    def test_05_a_list_is_wrapped_too_and_scalars_are_left_alone(self):
        self._insert(_poly_sql_param(['a', 'b']))
        self.env.cr.execute("SELECT v FROM poly_json_probe")
        self.assertEqual(self.env.cr.fetchone()[0], ['a', 'b'])

        for scalar in ('text', 3, 3.5, True, None):
            self.assertIs(_poly_sql_param(scalar), scalar)

    def test_06_every_static_default_is_in_the_column_format(self):
        """
        The contract `_poly_backfill_columns` now keeps, checked against a real base.

        Nothing it returns may still be in the write format: a value destined for a
        jsonb column must be wrapped or dropped, never a bare bool, dict or list.
        """
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning is not installed")
        Task = self.env['project.task']

        statics, _copied = Task._poly_backfill_columns('numa.planning.node')

        base = self.env['numa.planning.node']
        for column, value in statics.items():
            field = base._fields[column]
            if field.column_type and field.column_type[0] == 'jsonb':
                self.assertNotIsInstance(
                    value, (bool, dict, list),
                    "%s is a jsonb column; %r is the write format, not the column "
                    "format." % (column, value))
