from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestMaterialization(NumaVariantCommon):
    """On-demand creation of attribute values.

    Determinism is the whole point: the same payload must always yield the
    same value, or the master data fills up with near-duplicates and each one
    becomes a distinct product.
    """

    def test_same_reference_returns_the_same_value(self):
        first = self.attr_profile._get_or_create_value(
            {'reference': self.profile_l4040})
        second = self.attr_profile._get_or_create_value(
            {'reference': self.profile_l4040})
        self.assertEqual(first, second)
        self.assertTrue(first.is_materialized)

    def test_reference_accepts_a_model_id_tuple(self):
        """The controller sends the reference as (model, id), not a recordset."""
        value = self.attr_profile._get_or_create_value(
            {'reference': ('product.template', self.profile_l4040.id)})
        self.assertEqual(value._get_reference_record(), self.profile_l4040)

    def test_numbers_are_rounded_before_comparison(self):
        first = self.attr_length._get_or_create_value({'number': 1250.0})
        second = self.attr_length._get_or_create_value({'number': 1250.4})
        self.assertEqual(first, second)
        self.assertEqual(first.free_number, 1250.0)

    def test_numbers_beyond_rounding_are_distinct(self):
        first = self.attr_length._get_or_create_value({'number': 1250.0})
        second = self.attr_length._get_or_create_value({'number': 1252.0})
        self.assertNotEqual(first, second)

    def test_number_also_feeds_value_on_create(self):
        """A free number on a change_on_create attribute drives the variant
        dimension through the mechanism this module already had."""
        value = self.attr_length._get_or_create_value({'number': 1250.0})
        self.assertEqual(value.value_on_create, 1250.0)

    def test_text_is_case_sensitive(self):
        first = self.attr_legend._get_or_create_value({'char': 'Juan'})
        second = self.attr_legend._get_or_create_value({'char': 'JUAN'})
        self.assertNotEqual(first, second)

    def test_text_is_stripped(self):
        first = self.attr_legend._get_or_create_value({'char': 'Juan'})
        second = self.attr_legend._get_or_create_value({'char': '  Juan  '})
        self.assertEqual(first, second)

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.attr_legend._get_or_create_value({'char': '   '})

    def test_existing_curated_value_is_reused_not_duplicated(self):
        curated = self.env['product.attribute.value'].create({
            'name': 'Standard', 'attribute_id': self.attr_legend.id,
            'code_value': 'STD', 'canonical_key': 'Standard',
        })
        found = self.attr_legend._get_or_create_value({'char': 'Standard'})
        self.assertEqual(found, curated)
        self.assertFalse(found.is_materialized)

    def test_closed_attribute_rejects_unknown_values(self):
        self.attr_legend.allow_additional_values = False
        with self.assertRaises(ValidationError):
            self.attr_legend._get_or_create_value({'char': 'Anything'})

    def test_closed_attribute_still_returns_known_values(self):
        curated = self.env['product.attribute.value'].create({
            'name': 'Standard', 'attribute_id': self.attr_legend.id,
            'code_value': 'STD', 'canonical_key': 'Standard',
        })
        self.attr_legend.allow_additional_values = False
        self.assertEqual(
            self.attr_legend._get_or_create_value({'char': 'Standard'}),
            curated)

    def test_number_out_of_bounds_is_rejected(self):
        self.attr_length.number_min = 100.0
        self.attr_length.number_max = 6000.0
        with self.assertRaises(ValidationError):
            self.attr_length._get_or_create_value({'number': 7000.0})
        with self.assertRaises(ValidationError):
            self.attr_length._get_or_create_value({'number': 10.0})

    def test_payload_must_match_the_declared_type(self):
        with self.assertRaises(ValidationError):
            self.attr_length._get_or_create_value({'char': 'not a number'})
        with self.assertRaises(ValidationError):
            self.attr_profile._get_or_create_value({'char': 'not a record'})

    def test_reference_payload_must_match_the_declared_model(self):
        variant = self.profile_l4040.product_variant_ids[0]
        with self.assertRaises(ValidationError):
            self.attr_profile._get_or_create_value({'reference': variant})

    def test_canonical_key_is_stable_across_calls(self):
        first = self.attr_length._canonical_key({'number': 1250.0})
        second = self.attr_length._canonical_key({'number': 1250.2})
        self.assertEqual(first, second)
