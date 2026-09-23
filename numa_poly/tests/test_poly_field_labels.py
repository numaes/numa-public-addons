# -*- coding: utf-8 -*-
"""A dependent model's cloned fields must read in the user's language.

A polymorphic dependent gets an ``ir.model.fields`` row of its own for every
propagated field, and a ``.po`` names only the base model's row. The clone is
never named anywhere, so it keeps the source language for ever: a task form
showed all 38 propagated planning fields in English while the same fields on
the planning node read in Spanish. It looks like a translation that will not
load; it is a translation with nowhere to land.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'numa_poly')
class TestPolyFieldLabels(TransactionCase):

    def setUp(self):
        super().setUp()
        self.poly = self.env['ir.poly_base']
        self.lang = self.env['res.lang'].search(
            [('code', '!=', 'en_US'), ('active', '=', True)], limit=1)
        if not self.lang:
            self.skipTest("no second language active in this database")
        self.pair = self._a_pair_sharing_a_field()
        if not self.pair:
            self.skipTest("no polymorphic pair sharing a field in this registry")

    def _a_pair_sharing_a_field(self):
        Fields = self.env['ir.model.fields']
        for base_name, dep_name in self.poly._poly_dependent_pairs():
            base_fields = Fields.search([('model', '=', base_name)])
            for base_field in base_fields:
                dependent = Fields.search([('model', '=', dep_name),
                                           ('name', '=', base_field.name)],
                                          limit=1)
                if (dependent
                        and dependent.field_description
                        == base_field.field_description):
                    return base_field, dependent
        return None

    def _translate(self, field_row, text):
        """Set the second-language label the way a .po import does: en_US untouched.

        Neither an ORM write in another language nor `update_field_translations` is the
        same thing. When en_US is not an active language, both keep en_US in step with
        the latest value, so the base's source label changes and the clone no longer
        matches it. The translation importer only adds the language's key.
        """
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ir_model_fields SET field_description = field_description || "
            "jsonb_build_object(%s, %s) WHERE id = %s",
            (self.lang.code, text, field_row.id))
        field_row.invalidate_recordset(['field_description'])

    def test_the_pairs_are_found_at_all(self):
        self.assertTrue(self.poly._poly_dependent_pairs())

    def test_the_clone_adopts_the_base_translation(self):
        base_field, dependent = self.pair
        code = self.lang.code
        self._translate(base_field, 'Etiqueta base')

        self.poly._poly_sync_dependent_field_labels()
        dependent.invalidate_recordset()

        self.assertEqual(
            dependent.with_context(lang=code).field_description,
            'Etiqueta base')
        self.assertEqual(
            dependent.with_context(lang='en_US').field_description,
            base_field.with_context(lang='en_US').field_description,
            "the source label must not change")

    def test_a_relabelled_clone_is_left_alone(self):
        """A dependent that renames a field keeps what it said."""
        base_field, dependent = self.pair
        dependent.with_context(lang='en_US').field_description = 'Its own name'
        self._translate(base_field, 'Otra')

        self.poly._poly_sync_dependent_field_labels()
        dependent.invalidate_recordset()

        self.assertEqual(
            dependent.with_context(lang='en_US').field_description,
            'Its own name')

    def test_running_it_twice_writes_nothing_the_second_time(self):
        base_field, _dependent = self.pair
        self._translate(base_field, 'Dos')
        self.poly._poly_sync_dependent_field_labels()
        self.assertEqual(self.poly._poly_sync_dependent_field_labels(), 0)
