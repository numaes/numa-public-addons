# -*- coding: utf-8 -*-
"""The polymorphic list view and x2many widget, in a browser and on the server."""
from odoo.tests import Form, HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPolyUiBackend(TransactionCase):

    def test_01_subtypes_default_to_the_registered_hierarchy(self):
        models = [info['model'] for info in self.env['test.test1'].get_poly_subclasses_info()]
        self.assertEqual(sorted(models), ['test.test2', 'test.test3', 'test.test4'])

    def test_02_a_leaf_has_no_subtype(self):
        self.assertEqual(self.env['test.test4'].get_poly_subclasses_info(), [])

    def test_03_the_ui_gets_the_ir_model_ids(self):
        by_model = {i['model']: i for i in self.env['test.test1'].poly_ui_subclasses()}
        self.assertEqual(by_model['test.test3']['model_id'], self.env['ir.model']._get('test.test3').id)
        self.assertTrue(by_model['test.test3']['name'])

    def test_04_concrete_models_of_records(self):
        two = self.env['test.test2'].create({'a1': 'x', 'a3': 'y'})
        three = self.env['test.test3'].create({'a1': 'x', 'a4': 'z'})
        self.assertEqual(self.env['test.test1'].poly_ui_concrete_models([two.id, three.id]),
                         {two.id: 'test.test2', three.id: 'test.test3'})

    def test_05_a_base_create_with_a_payload_lands_on_the_concrete_model(self):
        """What the widget sends when the parent is saved."""
        site = self.env['test.poly.site'].create({
            'name': 'S',
            'item_ids': [(0, 0, {
                'concrete_model_id': self.env['ir.model']._get('test.test3').id,
                'poly_payload': '{"a1": "P1", "a4": "P4"}',
            })],
        })
        three = self.env['test.test3'].search([('site_id', '=', site.id)])
        self.assertEqual((three.a1, three.a4), ('P1', 'P4'))

    def test_06_a_parent_saved_with_lines_of_different_subtypes(self):
        """Each line lands on its own subtype, not all of them on the last one's."""
        IrModel = self.env['ir.model']
        site = self.env['test.poly.site'].create({
            'name': 'Mixed',
            'item_ids': [
                (0, 0, {'poly_payload': '{"a1": "two", "a3": "t3", "concrete_model_id": %d}'
                        % IrModel._get('test.test2').id}),
                (0, 0, {'poly_payload': '{"a1": "three", "a4": "t4", "concrete_model_id": %d}'
                        % IrModel._get('test.test3').id}),
            ],
        })
        by_a1 = {r.a1: r for r in site.item_ids}
        concrete = self.env['test.test1'].poly_ui_concrete_models(site.item_ids.ids)
        self.assertEqual(concrete[by_a1['two'].id], 'test.test2')
        self.assertEqual(concrete[by_a1['three'].id], 'test.test3')
        self.assertEqual(self.env['test.test3'].browse(by_a1['three'].id).a4, 't4')

    def test_07_client_annotations_in_the_payload_are_not_fields(self):
        site = self.env['test.poly.site'].create({
            'name': 'Annotated',
            'item_ids': [(0, 0, {'poly_payload': '{"a1": "x", "a4": "y", "__model": "test.test3", '
                                 '"concrete_model_id": %d}'
                                 % self.env['ir.model']._get('test.test3').id})],
        })
        self.assertEqual(self.env['test.test3'].search([('site_id', '=', site.id)]).a4, 'y')

    def test_08_the_root_shows_its_records_type(self):
        three = self.env['test.test3'].create({'a1': 'x', 'a4': 'z'})
        root = self.env['test.test1'].browse(three.id)
        self.assertEqual(root.concrete_model_id.model, 'test.test3')

    def test_09_a_subtype_without_a_form_of_its_own_can_be_saved(self):
        """Odoo's generated form shows `concrete_model_id`, which nobody can fill.

        It is read-only and computed from the shared base, so it must not be required
        either: "New" in a polymorphic list would open a form that cannot be saved.
        """
        self.assertFalse(self.env['test.test4'].fields_get(['concrete_model_id'])
                         ['concrete_model_id'].get('required'))
        with Form(self.env['test.test4']) as form:
            form.a1 = 'generated form'
        self.assertEqual(form.record.concrete_model_id.model, 'test.test4')


@tagged('post_install', '-at_install')
class TestPolyUiTours(HttpCase):

    def test_poly_list(self):
        self.env['test.test2'].create({'a1': 'Two A1', 'a3': 'Two A3'})
        action = self.env.ref('numa_poly_test.action_test_test1_poly_list')
        self.start_tour('/odoo/action-%s' % action.id, 'numa_poly_list_tour', login='admin')
        created = self.env['test.test3'].search([('a4', '=', 'Listed A4')])
        self.assertEqual(created.a1, 'Listed A1')

    def test_poly_widget(self):
        site = self.env['test.poly.site'].create({'name': 'Site A'})
        saved = self.env['test.test2'].create({'a1': 'Saved A1', 'a3': 'Saved A3', 'site_id': site.id})
        action = self.env.ref('numa_poly_test.action_test_poly_site')
        self.start_tour('/odoo/action-%s/%s' % (action.id, site.id), 'numa_poly_widget_tour', login='admin')
        created = self.env['test.test3'].search([('site_id', '=', site.id)])
        self.assertEqual((created.a1, created.a4), ('New A1', 'New A4'))
        self.assertEqual(saved.a3, 'Edited A3')
