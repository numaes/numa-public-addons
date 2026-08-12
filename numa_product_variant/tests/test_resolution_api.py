from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestResolutionApi(NumaVariantCommon):
    """Public API consumed by downstream modules.

    Pure mechanism: it returns the base material and the candidate variants,
    it never chooses one. Which physical strip a cut piece comes from is a
    bill-of-materials decision, the same way a D365 BOM line resolves its
    component while nesting stays a separate concern.
    """

    def setUp(self):
        super().setUp()
        self.cut = self._make_cut_piece_template()

    def test_get_attribute_reference_returns_the_base_template(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertEqual(
            variant.get_attribute_reference(self.attr_profile),
            self.profile_l4040)

    def test_get_attribute_reference_is_empty_for_a_plain_attribute(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertFalse(variant.get_attribute_reference(self.attr_color))

    def test_get_attribute_references_filters_by_model(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        found = variant.get_attribute_references(model='product.template')
        self.assertEqual(list(found.values()), [self.profile_l4040])
        self.assertEqual(list(found.keys()), [self.attr_profile])

    def test_get_attribute_references_excludes_other_models(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertFalse(
            variant.get_attribute_references(model='product.product'))

    def test_find_matching_variants_leaves_free_attributes_unconstrained(self):
        """Strip length exists on the base template but not on the cut piece,
        so both strip lengths must come back as candidates."""
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        candidates = variant.find_matching_variants(self.profile_l4040)
        strip_values = candidates.mapped(
            'product_template_attribute_value_ids.product_attribute_value_id')
        self.assertEqual(len(candidates), 2)
        self.assertIn(self.strip_6m, strip_values)
        self.assertIn(self.strip_45m, strip_values)

    def test_find_matching_variants_respects_shared_values(self):
        """A red cut piece must not match blue strips."""
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        candidates = variant.find_matching_variants(self.profile_l4040)
        colours = candidates.mapped(
            'product_template_attribute_value_ids.product_attribute_value_id')
        self.assertIn(self.color_red, colours)
        self.assertNotIn(self.color_blue, colours)

    def test_full_joinery_resolution(self):
        """The whole point, in two calls and no domain-specific code."""
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_blue, length=1250.0)
        base = variant.get_attribute_reference(self.attr_profile)
        candidates = variant.find_matching_variants(base)
        self.assertEqual(base, self.profile_l4040)
        self.assertEqual(len(candidates), 2)
        for candidate in candidates:
            values = candidate.product_template_attribute_value_ids.mapped(
                'product_attribute_value_id')
            self.assertIn(self.color_blue, values)
            self.assertIn(self.alloy_6063, values)
