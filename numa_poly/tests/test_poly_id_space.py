# -*- coding: utf-8 -*-
"""
A single allocator for the whole shared id space.

A polymorphic record and its components share an id, so all of those tables live in one and
the same space. Each one was born with its own ``SERIAL``, and therefore with its own
sequence: thirty allocators handing out over a single space. That they did not collide
depended on absolutely every insert going through poly's ``create()``, which supplies the
explicit id and never uses the column's ``DEFAULT``.

Any insert outside of that fired the table's own sequence, which knows nothing about the
shared space. And the symptom depended on the table: where ``MAX(id)`` was high it blew up
with a duplicate key, and where it was low it handed out 1, 2, 3 - free in that table and
taken in the space. That does not fail, it corrupts. Those are the 560 collisions in
production.

See doc/ID_SPACE.md.
"""
from odoo.tests import tagged, TransactionCase

from ..models.poly import POLY_ID_SEQUENCE


@tagged('post_install', '-at_install')
class TestPolyIdSpace(TransactionCase):

    def _shared_tables(self):
        """Every table in the space: that of each polymorphic model and those of its bases."""
        tables = set()
        for name in self.env.registry.models:
            model = self.env[name]
            getter = getattr(model, '_poly_get_depend_models', None)
            if not getter:
                continue
            depends = model._poly_get_depend_models()
            if not depends:
                continue
            if getattr(model, '_table', None):
                tables.add(model._table)
            for base_name in depends:
                if base_name in self.env and getattr(self.env[base_name], '_table', None):
                    tables.add(self.env[base_name]._table)
        return sorted(tables)

    def _column_default(self, table):
        self.env.cr.execute("""SELECT column_default FROM information_schema.columns
                                WHERE table_schema = current_schema()
                                  AND table_name = %s AND column_name = 'id'""", (table,))
        row = self.env.cr.fetchone()
        return (row and row[0]) or ''

    def test_01_every_shared_table_draws_from_the_one_allocator(self):
        """The structural invariant: no table of the space with a sequence of its own."""
        tables = self._shared_tables()
        if not tables:
            # numa_poly declares no polymorphic model of its own: the space exists only
            # once a module adopts it (numa_poly_test, numa_planning, ...). Nothing to
            # check here, which is not the same as the check passing.
            self.skipTest("no polymorphic model is installed; numa_poly_test covers this")

        propias = [t for t in tables if POLY_ID_SEQUENCE not in self._column_default(t)]

        self.assertFalse(
            propias,
            "these tables of the shared space still hand out ids on their own, and an "
            "insert that does not go through create() will give them an id already taken:\n  %s"
            % '\n  '.join('%s -> %s' % (t, self._column_default(t) or '(no default)')
                          for t in propias))

    def test_02_a_raw_insert_lands_in_the_shared_space(self):
        """The path that corrupted: inserting without going through the ORM.

        It used to draw from the table's own sequence. Now it draws from the single
        allocator, and the id it receives is free across the whole space.
        """
        cr = self.env.cr
        table = 'conversation_bot'
        if not self.env['ir.model'].sudo().search([('model', '=', 'conversation.bot')]):
            self.skipTest("conversation.bot is not installed")

        cr.execute("SELECT last_value FROM %s" % POLY_ID_SEQUENCE)
        antes = cr.fetchone()[0]
        cr.execute("INSERT INTO %s DEFAULT VALUES RETURNING id" % table)
        nuevo = cr.fetchone()[0]

        self.assertGreater(nuevo, antes - 1,
                           "the raw insert did not take its id from the single allocator")

        ocupadas = [t for t in self._shared_tables() if t != table
                    and self._id_exists(t, nuevo)]
        self.assertFalse(
            ocupadas,
            "the id %s the raw insert received was already in use in %s" % (nuevo, ocupadas))

    def _id_exists(self, table, record_id):
        self.env.cr.execute("SELECT 1 FROM %s WHERE id = %%s" % table, (record_id,))
        return bool(self.env.cr.fetchone())

    def test_03_claiming_is_idempotent(self):
        """It is re-applied on every update, so it has to be able to run twice.

        This used to compare against the PREVIOUS state of res.partner, taking for granted
        that it was already claimed. That depends on which modules are installed, not on the
        method: what is tested here is that the second pass does not change what the first
        one left behind.
        """
        model = self.env['res.partner']

        model._poly_claim_shared_id_space()
        tras_la_primera = self._column_default(model._table)
        model._poly_claim_shared_id_space()

        self.assertEqual(self._column_default(model._table), tras_la_primera,
                         "claiming twice changed something")
        self.assertIn(POLY_ID_SEQUENCE, tras_la_primera)

    def test_04_non_polymorphic_models_are_left_alone(self):
        """The shared space belongs to whoever takes part; the rest keep their own sequence."""
        default = self._column_default('ir_logging')
        self.assertNotIn(
            POLY_ID_SEQUENCE, default,
            "ir.logging takes part in no polymorphic hierarchy and should not be consuming "
            "from the shared allocator")
