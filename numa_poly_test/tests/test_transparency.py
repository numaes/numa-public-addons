# -*- coding: utf-8 -*-
"""
numa_poly transparency against real models from the fixtures module.

Complements the numa_poly tests, which cannot assume polymorphic models are installed:

- the polymorphic fixtures appear in the hierarchy map and keep poly's path;
- a shared M2M table is only tolerated between models of the same hierarchy;
- poly changes nothing for a plain model with a properly declared ``_inherits``;
- if the link field is not declared (Odoo 18 does not create it and boot would fail), poly
  drops the delegation in order to load, but now warns instead of keeping quiet;
- a broken subtype view is rejected at the final validation.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import config, mute_logger

from odoo.addons.numa_poly.models import poly as P

POLY = ('test.poly.base', 'test.poly.child.a', 'test.poly.child.b', 'test.poly.project',
        'test.test1', 'test.test2', 'test.test3', 'test.test4')
COMUNES = ('test.plain.delegate.parent', 'test.plain.delegate.child')


@tagged('post_install', '-at_install')
class TestPolyFixtureTransparency(TransactionCase):

    def test_01_fixtures_are_classified_correctly(self):
        mapa = self.registry._poly_hierarchy_model_names
        for name in POLY:
            self.assertIn(name, mapa)
            self.assertFalse(P._poly_is_outside_hierarchy(self.env[name]), name)
        for name in COMUNES:
            self.assertNotIn(name, mapa)
            self.assertTrue(P._poly_is_outside_hierarchy(self.env[name]), name)

    def test_02_shared_m2m_only_within_one_hierarchy(self):
        def jerarquia(name):
            return P._poly_hierarchy_names(type(self.env[name]))
        hijo = jerarquia('test.poly.child.a')
        self.assertIn('test.poly.base', hijo)
        for comun in ('res.currency', 'res.country') + COMUNES:
            self.assertFalse(jerarquia(comun), "%s should not have a poly hierarchy" % comun)

    def test_03_a_declared_plain_inherits_is_left_intact(self):
        Child = self.env['test.plain.delegate.child']
        self.assertEqual(Child._inherits, {'test.plain.delegate.parent': 'parent_id'})
        self.assertIn('parent_id', Child._fields)
        self.assertTrue(Child._fields['parent_id'].delegate)
        hijo = Child.create({'name': 'delegado', 'code': 'x'})
        self.assertEqual(hijo.parent_id.name, 'delegado')
        self.assertEqual(hijo.name, 'delegado')

    def test_04_a_broken_subtype_view_is_rejected_at_final_validation(self):
        previos = set(self.registry._pending_poly_views)

        def restaurar():
            self.registry._pending_poly_views.clear()
            self.registry._pending_poly_views.update(previos)
        self.addCleanup(restaurar)

        # [poly][20.0] "during loading" used to be registry._init = True;
        # it is now registry.loaded = False (registry.py:114).
        with patch.object(self.registry, 'loaded', False):
            vista = self.env['ir.ui.view'].create({
                'name': 'poly invalid subtype', 'model': 'test.poly.child.a', 'type': 'form',
                'arch': '<form><field name="x_no_existe_en_el_subtipo"/></form>'})
        self.assertIn(vista.id, self.registry._pending_poly_views)
        with patch.dict(config.options, {'poly_strict_view_validation': True}), \
                mute_logger('odoo.addons.numa_poly.models.poly'), \
                self.assertRaises(ValidationError) as ctx:
            self.registry._poly_finalize_view_validation(self.env.cr)
        self.assertIn('x_no_existe_en_el_subtipo', str(ctx.exception))

    def test_05_an_undeclared_link_field_is_dropped_loudly(self):
        """Odoo 18 does not create an ``_inherits`` link field: without declaring it boot fails.
        poly drops the delegation in order to load, and now it says so."""
        class ModeloSinEnlace:
            _name = 'test.poly.sin.enlace'
            _inherits = {'res.partner': 'partner_link_id'}
            _fields = {}

        with self.assertLogs('odoo.addons.numa_poly.models.poly', level='WARNING') as logs:
            P.poly_inherits_check(ModeloSinEnlace())
        self.assertEqual(ModeloSinEnlace._inherits, {})
        self.assertTrue(any('partner_link_id' in linea for linea in logs.output), logs.output)
