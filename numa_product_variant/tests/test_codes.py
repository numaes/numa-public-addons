from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestCodes(NumaVariantCommon):
    """Code generation for materialised values, and template value creation.

    The generated default_code composition — a fixed base plus per-attribute
    code elements — is the same one Infor LN uses for generated custom items,
    and it must not shift for the list attributes that already existed.
    """

    def test_reference_code_comes_from_the_referenced_base_code(self):
        value = self.attr_profile._get_or_create_value(
            {'reference': self.profile_l4040})
        self.assertEqual(value.code_value, 'L4040')

    def test_number_code_uses_the_attribute_format(self):
        value = self.attr_length._get_or_create_value({'number': 1250.0})
        self.assertEqual(value.code_value, '1250')

    def test_number_code_is_zero_padded(self):
        value = self.attr_length._get_or_create_value({'number': 80.0})
        self.assertEqual(value.code_value, '0080')

    def test_text_code_is_an_uppercase_slug_with_accents_folded(self):
        value = self.attr_legend._get_or_create_value({'char': 'Feliz día 2026'})
        self.assertEqual(value.code_value, 'FELIZDIA2026')

    def test_build_default_code_is_unchanged_for_list_attributes(self):
        """Regression: existing behaviour must not shift."""
        template = self._make_template(base_code='WIDGET')
        line = self.env['product.template.attribute.line'].create({
            'product_tmpl_id': template.id, 'attribute_id': self.attr_color.id,
            'value_ids': [(6, 0, self.color_blue.ids)],
        })
        ptav = line.product_template_value_ids
        self.assertEqual(template.build_default_code(ptav.ids), 'WIDGET.CB')

    def test_get_or_create_ptav_adds_the_value_to_the_line(self):
        template = self._make_cut_piece_template()
        line = template.attribute_line_ids.filtered(
            lambda candidate: candidate.attribute_id == self.attr_profile)
        ptav = line._get_or_create_ptav({'reference': self.profile_l4040})
        self.assertEqual(ptav.attribute_line_id, line)
        self.assertIn(ptav.product_attribute_value_id, line.value_ids)
        self.assertEqual(ptav._get_effective_reference(), self.profile_l4040)

    def test_get_or_create_ptav_is_idempotent(self):
        template = self._make_cut_piece_template()
        line = template.attribute_line_ids.filtered(
            lambda candidate: candidate.attribute_id == self.attr_length)
        first = line._get_or_create_ptav({'number': 800.0})
        second = line._get_or_create_ptav({'number': 800.0})
        self.assertEqual(first, second)

    def test_get_or_create_ptav_reactivates_an_archived_value(self):
        template = self._make_cut_piece_template()
        line = template.attribute_line_ids.filtered(
            lambda candidate: candidate.attribute_id == self.attr_length)
        first = line._get_or_create_ptav({'number': 800.0})
        first.write({'ptav_active': False})
        second = line._get_or_create_ptav({'number': 800.0})
        self.assertEqual(first, second)
        self.assertTrue(second.ptav_active)

    def test_configured_variant_gets_a_composed_default_code(self):
        template = self._make_cut_piece_template()
        variant = self._configure_cut_piece(
            template, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertTrue(variant.default_code.startswith('CUT.'))
        self.assertIn('PL4040', variant.default_code)
        self.assertIn('L0800', variant.default_code)
        self.assertIn('CR', variant.default_code)

    def test_default_code_is_rebuilt_when_the_combination_grows(self):
        """A value materialised into a line that already has variants attaches
        to them; the code must follow rather than stay stale."""
        template = self._make_cut_piece_template()
        variant = template.product_variant_ids[0]
        self.assertNotIn('PL4040', variant.default_code or '')
        line = template.attribute_line_ids.filtered(
            lambda candidate: candidate.attribute_id == self.attr_profile)
        line._get_or_create_ptav({'reference': self.profile_l4040})
        self.assertIn('PL4040', variant.default_code)

    def test_free_number_drives_the_variant_length(self):
        """change_on_create + a free numeric value: the cut piece gets its
        length without any domain-specific code."""
        template = self._make_cut_piece_template()
        variant = self._configure_cut_piece(
            template, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertEqual(variant.product_length, 800.0)
