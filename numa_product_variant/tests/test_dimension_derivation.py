from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestDimensionDerivation(NumaVariantCommon):
    """A configured variant must reach the database with every magnitude set.

    ``change_on_create`` writes a dimension; surface, volume and weight follow
    from it through ``numa_physical_product``. This module used to carry its
    own copy of the weight derivation under a different name, so the form and
    the configurator produced different weights for the same variant.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Attribute = cls.env['product.attribute']
        Value = cls.env['product.attribute.value']

        cls.attr_sheet_length = Attribute.create({
            'name': 'Sheet length', 'create_variant': 'always',
            'code_identifier': 'L', 'value_type': 'number',
            'change_on_create': 'length', 'number_uom': 'm',
            'allow_additional_values': True,
            'number_rounding': 0.001,
        })
        cls.attr_sheet_width = Attribute.create({
            'name': 'Sheet width', 'create_variant': 'always',
            'code_identifier': 'W', 'value_type': 'number',
            'change_on_create': 'width', 'number_uom': 'm',
            'allow_additional_values': True,
            'number_rounding': 0.001,
        })
        cls.length_3 = cls.attr_sheet_length._get_or_create_value({'number': 3.0})
        cls.width_2 = cls.attr_sheet_width._get_or_create_value({'number': 2.0})

        # A value that scales the weight, to pin the multiplier hook.
        cls.attr_finish = Attribute.create({
            'name': 'Finish', 'create_variant': 'always', 'code_identifier': 'F',
        })
        cls.finish_heavy = Value.create({
            'name': 'Heavy', 'attribute_id': cls.attr_finish.id,
            'code_value': 'H', 'weight_factor': 2.0,
        })

    def _sheet_template(self, extra_lines=(), **vals):
        base = {
            'name': 'Sheet',
            'type': 'consu',
            'base_code': 'SH',
            'attribute_line_ids': [
                (0, 0, {'attribute_id': self.attr_sheet_length.id,
                        'value_ids': [(6, 0, self.length_3.ids)]}),
                (0, 0, {'attribute_id': self.attr_sheet_width.id,
                        'value_ids': [(6, 0, self.width_2.ids)]}),
            ] + list(extra_lines),
        }
        base.update(vals)
        return self.env['product.template'].create(base)

    def test_configured_variant_gets_its_surface(self):
        variant = self._sheet_template().product_variant_ids
        self.assertEqual(len(variant), 1)
        self.assertEqual(variant.product_length, 3.0)
        self.assertEqual(variant.product_width, 2.0)
        self.assertEqual(variant.surface, 6.0)

    def test_configured_sheet_is_not_costed_at_zero(self):
        """The failure the derivation fix exists for."""
        variant = self._sheet_template(price_base='surface').product_variant_ids
        self.assertEqual(variant._get_price_qty(2.0), 12.0)

    def test_weight_follows_the_derived_surface(self):
        variant = self._sheet_template(
            weight_kind='surface', weight_factor=1.5).product_variant_ids
        self.assertEqual(variant.weight, 9.0)

    def test_attribute_value_weight_factor_scales_the_weight(self):
        variant = self._sheet_template(
            extra_lines=[(0, 0, {'attribute_id': self.attr_finish.id,
                                 'value_ids': [(6, 0, self.finish_heavy.ids)]})],
            weight_kind='surface', weight_factor=1.5).product_variant_ids
        self.assertEqual(variant.weight, 18.0)

    def test_a_zero_weight_factor_is_read_as_no_factor(self):
        """A value predating the field carries 0.0, which is not weightless."""
        legacy = self.env['product.attribute.value'].create({
            'name': 'Legacy', 'attribute_id': self.attr_finish.id,
            'code_value': 'LG', 'weight_factor': 0.0,
        })
        variant = self._sheet_template(
            extra_lines=[(0, 0, {'attribute_id': self.attr_finish.id,
                                 'value_ids': [(6, 0, legacy.ids)]})],
            weight_kind='surface', weight_factor=1.5).product_variant_ids
        self.assertEqual(variant.weight, 9.0)


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestConfigure(NumaVariantCommon):
    """`configure` es la operacion que todo configurador necesita.

    Estaba escrita dentro de una familia de un cliente; no tiene nada de esa
    familia. Pedir la variante que corresponde a un juego de valores, creandola
    si no existe y devolviendo la que hay si ya existe, es lo que hace cualquier
    configurador de cualquier dominio.
    """

    def setUp(self):
        super().setUp()
        Attribute = self.env['product.attribute']
        self.largo = Attribute.create({
            'name': 'Largo', 'create_variant': 'dynamic',
            'code_identifier': 'LG', 'value_type': 'number',
            'number_rounding': 1.0, 'allow_additional_values': True,
        })
        self.material = Attribute.create({
            'name': 'Material', 'create_variant': 'dynamic',
            'code_identifier': 'MT', 'value_type': 'reference',
            'reference_model': 'product.template',
            'allow_additional_values': True,
        })
        self.perfil = self.env['product.template'].create(
            {'name': 'Perfil X', 'type': 'consu'})
        self.pieza = self.env['product.template'].create({
            'name': 'Pieza', 'type': 'consu', 'base_code': 'PZ',
            'attribute_line_ids': [
                (0, 0, {'attribute_id': self.largo.id}),
                (0, 0, {'attribute_id': self.material.id}),
            ],
        })

    def test_it_gives_a_variant(self):
        variant = self.pieza.configure({self.largo: {'number': 1200},
                                        self.material: {'reference': self.perfil}})
        self.assertTrue(variant)
        self.assertEqual(variant.product_tmpl_id, self.pieza)

    def test_asking_twice_gives_the_same_product(self):
        payloads = {self.largo: {'number': 1200},
                    self.material: {'reference': self.perfil}}
        self.assertEqual(self.pieza.configure(payloads),
                         self.pieza.configure(dict(payloads)))

    def test_a_different_value_is_a_different_product(self):
        one = self.pieza.configure({self.largo: {'number': 1200},
                                    self.material: {'reference': self.perfil}})
        other = self.pieza.configure({self.largo: {'number': 1201},
                                      self.material: {'reference': self.perfil}})
        self.assertNotEqual(one, other)

    def test_the_rounding_decides_what_counts_as_the_same(self):
        self.largo.number_rounding = 10.0
        one = self.pieza.configure({self.largo: {'number': 1200},
                                    self.material: {'reference': self.perfil}})
        other = self.pieza.configure({self.largo: {'number': 1202},
                                      self.material: {'reference': self.perfil}})
        self.assertEqual(one, other)

    def test_an_attribute_the_product_does_not_have_is_reported(self):
        other = self.env['product.attribute'].create({
            'name': 'Ajeno', 'create_variant': 'dynamic',
            'code_identifier': 'AJ', 'value_type': 'number',
            'number_rounding': 1.0, 'allow_additional_values': True,
        })
        with self.assertRaises(UserError):
            self.pieza.configure({other: {'number': 1}})
