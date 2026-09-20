# -*- coding: utf-8 -*-
"""
Relational and reference fields inherited from a polymorphic base.

Both invariants come from real failures, and both used to be "covered" by tests
that could never run: they lived in `numa_poly/tests/test_poly_setup.py` and
`test_poly_reference_fields.py`, guarded by `skipTest` on models and fields that
nothing declared. They were green lines, not tests.

1. A relational field of the base must reach the concrete model as a *related*
   field through the link, never as storage of its own. When Odoo's incremental
   loader injected an inherited many2many as stored on the concrete model,
   reading it went looking for a relation table that does not exist
   (`project_task_resource_rel`, in the case that was reported).

2. A `fields.Reference` written on a polymorphic model must come back out.
   `fields.Reference` subclasses `fields.Selection`, so the guard that filters
   cross-model Selection pollution compared the stored `"model,id"` string
   against a set of bare model names, rejected it, and dropped the value with
   only a warning in the log.
"""
from odoo.tests.common import TransactionCase, tagged

BASE = 'test.poly.base'
CONCRETO = 'test.poly.child.a'


@tagged('post_install', '-at_install')
class TestPolyInheritedRelational(TransactionCase):

    def test_01_an_inherited_many2many_is_related_and_not_stored(self):
        campo = self.env[CONCRETO]._fields['base_partner_ids']
        self.assertTrue(campo.related,
                        "a many2many of the base must reach the concrete model as related")
        self.assertFalse(campo.store,
                         "storing it on the concrete model asks for a relation table "
                         "that only the base has")
        self.assertEqual(campo.related, 'base_id.base_partner_ids',
                         "the related path must go through the link field")

    def test_02_it_owns_no_column_and_no_relation_table(self):
        """What the failure looked like from SQL."""
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'test_poly_child_a' AND column_name = 'base_partner_ids'
        """)
        self.assertIsNone(self.env.cr.fetchone(),
                          "the inherited many2many took a column on the concrete table")

        campo_base = self.env[BASE]._fields['base_partner_ids']
        self.env.cr.execute("""
            SELECT table_name FROM information_schema.tables WHERE table_name = %s
        """, (campo_base.relation,))
        self.assertIsNotNone(self.env.cr.fetchone(),
                             "the base's relation table is missing: %s" % campo_base.relation)

    def test_03_it_can_be_written_and_read_through_the_link(self):
        socio = self.env['res.partner'].create({'name': 'Socio de prueba'})
        registro = self.env[CONCRETO].create({
            'child_a_field': 'concreto',
            'base_partner_ids': [(6, 0, socio.ids)],
        })
        self.assertEqual(registro.base_partner_ids, socio)

        self.env.invalidate_all()
        self.assertEqual(registro.base_partner_ids, socio,
                         "reading it back from the database failed")
        self.assertEqual(self.env[BASE].browse(registro.id).base_partner_ids, socio,
                         "the value did not land on the base row")

    def test_04_a_reference_survives_create_on_a_polymorphic_model(self):
        socio = self.env['res.partner'].create({'name': 'Referenciado'})
        registro = self.env[CONCRETO].create({'ref_field': 'res.partner,%s' % socio.id})
        self.assertEqual(registro.ref_field, socio)

        self.env.invalidate_all()
        self.assertEqual(registro.ref_field, socio,
                         "the reference was dropped between the write and the read")
