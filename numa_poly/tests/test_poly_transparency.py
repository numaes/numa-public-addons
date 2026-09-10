# -*- coding: utf-8 -*-
"""
Transparencia de poly hacia los modelos que no lo usan.

poly parchea ``_Relational.__get__``, ``One2many.__get__`` y ``Many2many.read`` para todos los
modelos. El atajo que debía devolver a los no polimórficos al camino original de Odoo estaba
muerto: buscaba ``_depend_models`` en el ``__dict__`` de cada base, y ``PolyBase`` —que está en el
MRO de todos— lo declara en None. Toda lectura relacional de cualquier modelo tomaba el camino de
poly: 839 modelos en una instalación real, cuando los polimórficos eran 43.

Estos tests fijan el criterio correcto (el VALOR de ``_depend_models``, no su presencia) y las
condiciones en las que se habilita el atajo: registry listo y mapa de jerarquías construido.
"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged, TransactionCase

from ..models import poly as P


@tagged('post_install', '-at_install')
class TestPolyTransparency(TransactionCase):

    def _expected_hierarchy(self):
        """Cálculo independiente del mapa, para no testear la función contra sí misma."""
        names = set()
        for name in list(self.registry):
            for base in type(self.env[name]).mro():
                declared = base.__dict__.get('_depend_models')
                if declared is None:
                    continue
                names.add(name)
                names.update(declared or {})
        return names

    def test_01_polybase_declares_none_for_everyone(self):
        """La trampa: la presencia del atributo no distingue a nadie."""
        self.assertIn('_depend_models', P.PolyBase.__dict__)
        self.assertIsNone(P.PolyBase.__dict__['_depend_models'])
        self.assertIn(P.PolyBase, type(self.env['res.currency']).mro())

    def test_02_the_map_is_built_and_matches(self):
        mapa = self.registry._poly_hierarchy_model_names
        self.assertIsInstance(mapa, frozenset,
                              "el mapa de jerarquías no se construyó al final del setup")
        self.assertEqual(set(mapa), self._expected_hierarchy())
        self.assertLess(len(mapa), len(self.registry),
                        "todos los modelos figuran como polimórficos: el criterio volvió a ser "
                        "la presencia del atributo")

    def test_03_non_polymorphic_models_are_outside(self):
        for name in ('res.currency', 'ir.logging', 'res.country'):
            self.assertNotIn(name, self.registry._poly_hierarchy_model_names)
            self.assertTrue(P._poly_is_outside_hierarchy(self.env[name]),
                            "%s no participa de ninguna jerarquía y no toma el camino original" % name)

    def test_04_polymorphic_models_keep_the_poly_path(self):
        mapa = self.registry._poly_hierarchy_model_names
        if not mapa:
            self.skipTest("no hay modelos polimórficos instalados")
        for name in sorted(mapa):
            if name in self.env:
                self.assertFalse(P._poly_is_outside_hierarchy(self.env[name]), name)

    def test_05_no_shortcut_while_the_registry_is_not_ready(self):
        currency = self.env['res.currency']
        self.assertTrue(P._poly_is_outside_hierarchy(currency))
        with patch.object(self.registry, 'ready', False):
            self.assertFalse(P._poly_is_outside_hierarchy(currency),
                             "durante el setup todos deben tomar el camino tolerante")
        with patch.object(self.registry, '_poly_hierarchy_model_names', None):
            self.assertFalse(P._poly_is_outside_hierarchy(currency),
                             "sin mapa no hay certeza, y sin certeza no hay atajo")

    def test_06_non_recordsets_never_take_the_shortcut(self):
        self.assertFalse(P._poly_is_outside_hierarchy(object()))
        self.assertFalse(P._poly_is_outside_hierarchy(None))

    def test_07_relational_reads_are_unchanged(self):
        """El camino original da lo mismo que la base de datos, y el acceso por clase sigue
        devolviendo el campo (el caso que motivó las guardas de poly)."""
        usd = self.env.ref('base.USD')
        expected = self.env['res.currency.rate'].search([('currency_id', '=', usd.id)])
        self.assertEqual(set(usd.rate_ids.ids), set(expected.ids))
        self.assertIn(self.env.company, self.env.user.company_ids)
        self.assertIsInstance(type(self.env['res.currency']).rate_ids, fields.One2many)

    def test_08_a_runtime_setup_rebuilds_the_map(self):
        """Crear un campo manual reconstruye el registry en caliente: el mapa tiene que volver."""
        model = self.env['ir.model']._get('res.currency')
        self.env['ir.model.fields'].create({
            'name': 'x_poly_probe', 'model_id': model.id, 'ttype': 'char',
            'field_description': 'poly probe'})
        mapa = self.registry._poly_hierarchy_model_names
        self.assertIsInstance(mapa, frozenset, "después de un setup en caliente no hay mapa")
        self.assertEqual(set(mapa), self._expected_hierarchy())
        self.assertTrue(P._poly_is_outside_hierarchy(self.env['res.currency']))
