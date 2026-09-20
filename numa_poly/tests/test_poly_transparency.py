# -*- coding: utf-8 -*-
"""
Transparency of poly towards the models that do not use it.

poly patches ``_Relational.__get__``, ``One2many.__get__`` and ``Many2many.read`` for every
model. The shortcut that was meant to send non-polymorphic models back to Odoo's original path
was dead: it looked up ``_depend_models`` in each base's ``__dict__``, and ``PolyBase`` -which is
in everyone's MRO- declares it as None. Every relational read of every model took poly's path:
839 models in a real installation, when the polymorphic ones were 43.

These tests pin down the correct criterion (the VALUE of ``_depend_models``, not its presence)
and the conditions under which the shortcut is enabled: registry ready and hierarchy map built.
"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged, TransactionCase

from ..models import poly as P


@tagged('post_install', '-at_install')
class TestPolyTransparency(TransactionCase):

    def _expected_hierarchy(self):
        """Computed independently of the map, so the function is not tested against itself."""
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
        """The trap: the presence of the attribute tells nobody apart."""
        self.assertIn('_depend_models', P.PolyBase.__dict__)
        self.assertIsNone(P.PolyBase.__dict__['_depend_models'])
        self.assertIn(P.PolyBase, type(self.env['res.currency']).mro())

    def test_02_the_map_is_built_and_matches(self):
        mapa = self.registry._poly_hierarchy_model_names
        self.assertIsInstance(mapa, frozenset,
                              "the hierarchy map was not built at the end of the setup")
        self.assertEqual(set(mapa), self._expected_hierarchy())
        self.assertLess(len(mapa), len(self.registry),
                        "every model shows up as polymorphic: the criterion went back to "
                        "being the presence of the attribute")

    def test_03_non_polymorphic_models_are_outside(self):
        for name in ('res.currency', 'ir.logging', 'res.country'):
            self.assertNotIn(name, self.registry._poly_hierarchy_model_names)
            self.assertTrue(P._poly_is_outside_hierarchy(self.env[name]),
                            "%s takes part in no hierarchy and is not taking the original path" % name)

    def test_04_polymorphic_models_keep_the_poly_path(self):
        mapa = self.registry._poly_hierarchy_model_names
        if not mapa:
            self.skipTest("no polymorphic models are installed")
        for name in sorted(mapa):
            if name in self.env:
                self.assertFalse(P._poly_is_outside_hierarchy(self.env[name]), name)

    def test_05_no_shortcut_while_the_registry_is_not_ready(self):
        currency = self.env['res.currency']
        self.assertTrue(P._poly_is_outside_hierarchy(currency))
        with patch.object(self.registry, 'ready', False):
            self.assertFalse(P._poly_is_outside_hierarchy(currency),
                             "during the setup everyone must take the tolerant path")
        with patch.object(self.registry, '_poly_hierarchy_model_names', None):
            self.assertFalse(P._poly_is_outside_hierarchy(currency),
                             "without a map there is no certainty, and without certainty there is no shortcut")

    def test_06_non_recordsets_never_take_the_shortcut(self):
        self.assertFalse(P._poly_is_outside_hierarchy(object()))
        self.assertFalse(P._poly_is_outside_hierarchy(None))

    def test_07_relational_reads_are_unchanged(self):
        """The original path gives the same as the database, and class-level access still
        returns the field (the case that motivated poly's guards)."""
        usd = self.env.ref('base.USD')
        expected = self.env['res.currency.rate'].search([('currency_id', '=', usd.id)])
        self.assertEqual(set(usd.rate_ids.ids), set(expected.ids))
        self.assertIn(self.env.company, self.env.user.company_ids)
        self.assertIsInstance(type(self.env['res.currency']).rate_ids, fields.One2many)

    def test_08_a_runtime_setup_rebuilds_the_map(self):
        """Creating a manual field rebuilds the registry hot: the map has to come back."""
        model = self.env['ir.model']._get('res.currency')
        self.env['ir.model.fields'].create({
            'name': 'x_poly_probe', 'model_id': model.id, 'ttype': 'char',
            'field_description': 'poly probe'})
        mapa = self.registry._poly_hierarchy_model_names
        self.assertIsInstance(mapa, frozenset, "there is no map after a hot setup")
        self.assertEqual(set(mapa), self._expected_hierarchy())
        self.assertTrue(P._poly_is_outside_hierarchy(self.env['res.currency']))
