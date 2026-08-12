from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestAttributeTyping(NumaVariantCommon):
    """Type declaration on product.attribute.

    `value_type` is orthogonal to `create_variant` and to `display_type`: it
    says what kind of data a value carries, not how it is rendered nor whether
    it produces a variant.
    """

    def test_default_value_type_is_char(self):
        """Existing attributes keep behaving as plain text attributes."""
        self.assertEqual(self.attr_color.value_type, 'char')
        self.assertFalse(self.attr_color.allow_additional_values)

    def test_reference_attribute_declares_a_model(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type',
            'create_variant': 'dynamic',
            'code_identifier': 'P',
            'value_type': 'reference',
            'reference_model': 'product.template',
        })
        self.assertEqual(attr.reference_model, 'product.template')

    def test_reference_attribute_requires_a_model(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken reference',
                'value_type': 'reference',
            })

    def test_number_bounds_must_be_ordered(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken bounds',
                'value_type': 'number',
                'number_min': 100.0,
                'number_max': 10.0,
            })

    def test_number_rounding_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken rounding',
                'value_type': 'number',
                'number_rounding': 0.0,
            })
