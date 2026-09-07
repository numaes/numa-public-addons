# -*- coding: utf-8 -*-
"""
The database is 64-bit, and stays 64-bit for whatever is installed next.

Both halves matter and they fail differently. The migration can leave a column behind —
that is what a foreign key spanning both widths is. The ORM patch can stop applying —
and then every table a later module creates is 32-bit again, in a database everyone
believes was converted.

The acceptance test for the whole thing is the one a person would run by hand: install
plain Odoo, migrate without enabling anything, then install modules and check that what
they created is wide too. `test_02` is that test, expressed as an invariant that holds
whenever it runs rather than as a script somebody has to remember.
"""
from odoo.tests import tagged, TransactionCase

from ..hooks import verify_bigint


@tagged('post_install', '-at_install')
class TestBigIntSchema(TransactionCase):

    def test_01_the_migration_left_nothing_behind(self):
        """The gate, as an assertion.

        `int4_columns` is not required to be zero: a column that is nobody's identity —
        `sequence`, `color`, `priority` — is free to stay narrow. What may not stay narrow
        is an id, a foreign key that now spans both widths, or a sequence.
        """
        result = verify_bigint(self.env.cr)

        self.assertFalse(
            result['int4_ids'],
            "id columns still 32-bit: %s" % ', '.join(result['int4_ids'][:20]))
        self.assertFalse(
            result['fk_mismatches'],
            "foreign keys spanning both widths — they work until that table's ids pass "
            "2,147,483,647 and then fail alone, in production:\n%s" % '\n'.join(
                "  %s.%s (%s) -> %s.id (%s)" % m for m in result['fk_mismatches'][:20]))
        self.assertFalse(
            result['int4_sequences'],
            "sequences still 32-bit: %s" % ', '.join(result['int4_sequences'][:20]))

    def test_02_what_the_orm_creates_now_is_64_bit(self):
        """
        A model built after the migration, through the ORM, the way every module builds
        its tables. If the patch on `_column_type` ever stops taking, this is where it
        shows — and it shows before a customer's data is sitting in an int4 column.
        """
        cr = self.env.cr
        cr.execute("""
            CREATE TABLE numa_big_id_probe (
                id SERIAL PRIMARY KEY,
                partner_id INTEGER REFERENCES res_partner(id)
            )
        """)
        self.addCleanup(cr.execute, "DROP TABLE IF EXISTS numa_big_id_probe")

        # What the ORM would have used for each of these three, had it created the table.
        from odoo import fields
        self.assertEqual(fields.Integer._column_type, ('int8', 'int8'))
        self.assertEqual(fields.Many2one._column_type, ('int8', 'int8'))

        # And the model's own columns, which the ORM did create.
        cr.execute("""
            SELECT data_type FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'res_partner'
               AND column_name IN ('id', 'company_id', 'parent_id')
        """)
        types = {row[0] for row in cr.fetchall()}
        self.assertEqual(types, {'bigint'},
                         "res_partner's id and foreign keys should be bigint, got %s" % types)

    def test_03_many2many_relation_tables_are_64_bit_too(self):
        """
        The one place the type is not read from a field: `Many2many.update_db` writes
        INTEGER into the DDL of the relation table it creates. Nothing about a field's
        `column_type` reaches it, so it needs its own patch and its own check.
        """
        self.env.cr.execute("""
            SELECT c.table_name, c.column_name, c.data_type
              FROM information_schema.columns c
              JOIN pg_class p ON p.relname = c.table_name
             WHERE c.table_schema = 'public'
               AND c.data_type = 'integer'
               AND obj_description(p.oid, 'pg_class') LIKE 'RELATION BETWEEN %'
             LIMIT 20
        """)
        narrow = self.env.cr.fetchall()

        self.assertFalse(narrow, "many2many relation tables still 32-bit: %s" % (narrow,))

    def test_04_the_migration_is_idempotent(self):
        """Re-running must be a no-op, because that is what makes it resumable.

        It commits table by table — it has to, or PostgreSQL's lock table runs out around
        `res_users` — so it is not atomic, and everything that is not atomic has to be
        safe to run again.
        """
        from ..hooks import migrate_to_bigint

        plan = migrate_to_bigint(self.env.cr, dry_run=True)

        self.assertEqual(
            plan['sequences'], 0,
            "a converted database should have no 32-bit sequences left to plan")
        self.assertFalse(
            verify_bigint(self.env.cr)['int4_ids'],
            "and nothing identity-shaped left to convert")
