# -*- coding: utf-8 -*-
"""
Transparencia de numa_poly con modelos reales del módulo de fixtures.

Complementa los tests de numa_poly, que no pueden asumir modelos polimórficos instalados:

- los fixtures polimórficos figuran en el mapa de jerarquías y conservan el camino de poly;
- una tabla M2M compartida solo se tolera entre modelos de la misma jerarquía;
- a un modelo común con ``_inherits`` bien declarado poly no le cambia nada;
- si el campo de enlace no está declarado (Odoo 18 no lo crea solo y el arranque caería), poly
  descarta la delegación para poder cargar, pero ahora lo avisa en vez de callarlo;
- una vista rota de un subtipo se rechaza en la validación final.
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
            self.assertFalse(jerarquia(comun), "%s no debería tener jerarquía poly" % comun)

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

        with patch.object(self.registry, '_init', True):
            vista = self.env['ir.ui.view'].create({
                'name': 'poly subtipo inválida', 'model': 'test.poly.child.a', 'type': 'form',
                'arch': '<form><field name="x_no_existe_en_el_subtipo"/></form>'})
        self.assertIn(vista.id, self.registry._pending_poly_views)
        with patch.dict(config.options, {'poly_strict_view_validation': True}), \
                mute_logger('odoo.addons.numa_poly.models.poly'), \
                self.assertRaises(ValidationError) as ctx:
            self.registry._poly_finalize_view_validation(self.env.cr)
        self.assertIn('x_no_existe_en_el_subtipo', str(ctx.exception))

    def test_05_an_undeclared_link_field_is_dropped_loudly(self):
        """Odoo 18 no crea el campo de enlace de un ``_inherits``: sin declararlo el arranque cae.
        poly descarta la delegación para poder cargar, y ahora lo dice."""
        class ModeloSinEnlace:
            _name = 'test.poly.sin.enlace'
            _inherits = {'res.partner': 'partner_link_id'}
            _fields = {}

        with self.assertLogs('odoo.addons.numa_poly.models.poly', level='WARNING') as logs:
            P.poly_inherits_check(ModeloSinEnlace())
        self.assertEqual(ModeloSinEnlace._inherits, {})
        self.assertTrue(any('partner_link_id' in linea for linea in logs.output), logs.output)
