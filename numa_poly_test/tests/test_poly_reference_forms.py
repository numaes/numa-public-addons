# -*- coding: utf-8 -*-
"""
The two faces of a ``PolyReference``: the value in Python and its SQL form.

A PolyReference has no column. Base and derived share the id, so the "link" to
the base is the record's own id, and that is stated twice: with ``compute``
—the value— and with ``compute_sql`` —the same thing as a query expression,
which is what allows the field to be used in a domain (``domains.py:1021``
requires ``store`` or ``compute_sql``)—.

Odoo demands both together: ``compute_sql`` without ``compute`` warns *"makes
sense only if ... is a computed field"* (``fields.py:471-473``). numa_poly
declared only the second one because it derived the value in a ``__get__`` of its
own, in parallel with the framework's.

``test_02`` is the one that matters, and it comes from having got this wrong:
declaring the ``compute`` and leaving the ``__get__`` in place made the warning
disappear **without the compute ever running** —measured: zero calls reading by
attribute, by ``read()`` and by ``mapped()``—. A compute that is declared and dead
is decoration that silences a warning, which is exactly what the warning meant to
prevent.
"""
from odoo.tests.common import TransactionCase, tagged

CONCRETO = 'test.poly.child.a'
VINCULO = 'base_id'


@tagged('post_install', '-at_install')
class TestPolyReferenceForms(TransactionCase):

    def _campo(self):
        return self.env[CONCRETO]._fields[VINCULO]

    def test_01_the_reference_declares_both_forms(self):
        campo = self._campo()
        self.assertTrue(campo.compute,
                        "without compute, compute_sql has nothing to be the translation "
                        "of, and Odoo warns when building the field")
        self.assertTrue(campo.compute_sql,
                        "without compute_sql the field cannot be used in a domain")

    def test_02_the_python_side_is_the_one_that_actually_runs(self):
        """The compute must not be decoration: it has to run on read."""
        campo = self._campo()
        llamadas = []
        original = campo.compute

        def espia(records):
            llamadas.append(records._name)
            return original(records)

        espia.__name__ = 'espia_poly_reference'
        self.patch(campo, 'compute', espia)

        registro = self.env[CONCRETO].create({'base_field': 'dato'})
        self.env.invalidate_all()
        self.assertTrue(registro[VINCULO])
        self.assertTrue(llamadas, "reading the link did not run the declared compute")

    def test_03_the_sql_form_agrees_with_the_python_one(self):
        """Both faces have to give the same answer.

        Reading uses the compute; searching uses compute_sql and never goes
        through Python. If they diverge, a domain returns records that the
        attribute contradicts.
        """
        registro = self.env[CONCRETO].create({'base_field': 'dato'})
        self.env.flush_all()
        base = registro[VINCULO]
        self.assertTrue(base)

        encontrados = self.env[CONCRETO].search(
            [(VINCULO, '=', base.id), ('id', 'in', registro.ids)])
        self.assertEqual(encontrados, registro,
                         "the domain does not find what the attribute asserts")

        # The dotted path, which is the one that uses the link's SQL expression.
        por_la_base = self.env[CONCRETO].search(
            [('%s.base_field' % VINCULO, '=', 'dato'), ('id', 'in', registro.ids)])
        self.assertEqual(por_la_base, registro)

    def test_04_reading_the_link_over_many_records_is_one_query(self):
        """The link resolves without going to the database: it is the id itself."""
        registros = self.env[CONCRETO].create(
            [{'base_field': 'n%s' % n} for n in range(10)])
        self.env.invalidate_all()
        with self.assertQueryCount(__system__=0):
            bases = registros.mapped(VINCULO)
        self.assertEqual(len(bases), 10)
