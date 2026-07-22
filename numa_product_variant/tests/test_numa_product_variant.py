from odoo.tests.common import tagged
from .common import NumaVariantCommon


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestNumaProductVariant(NumaVariantCommon):
    """Characterization tests for the pre-existing numa_product_variant logic."""

    def test_category_default_attributes_recursive(self):
        """get_default_attribute_lines returns own + parent category attributes."""
        child = self.env['product.category'].create({
            'name': 'Child', 'parent_id': self.category.id,
        })
        attrs = child.get_default_attribute_lines()
        self.assertIn(self.attr_color, attrs)
        self.assertIn(self.attr_size, attrs)

    def test_template_create_assigns_category_attributes(self):
        """Creating a template in a category auto-populates its attribute lines."""
        tmpl = self._make_template(categ_id=self.category.id)
        line_attrs = tmpl.attribute_line_ids.mapped('attribute_id')
        self.assertIn(self.attr_color, line_attrs)
        self.assertIn(self.attr_size, line_attrs)

    def test_template_write_changes_category_attributes(self):
        """Changing categ_id assigns the new category's attributes."""
        tmpl = self._make_template()
        tmpl.write({'categ_id': self.category.id})
        line_attrs = tmpl.attribute_line_ids.mapped('attribute_id')
        self.assertIn(self.attr_color, line_attrs)

    def test_build_default_code_skips_default_value(self):
        """build_default_code concatenates base_code + attribute codes, skipping
        values equal to the attribute's default_value."""
        self.attr_color.default_value = self.color_red
        tmpl = self._make_template(
            base_code='WIDGET',
            attribute_line_ids=[(0, 0, {
                'attribute_id': self.attr_color.id,
                'value_ids': [(6, 0, (self.color_red + self.color_blue).ids)],
            })],
        )
        blue_variant = tmpl.product_variant_ids.filtered(
            lambda p: self.color_blue in
            p.product_template_attribute_value_ids.product_attribute_value_id
        )
        code = tmpl.build_default_code(
            blue_variant.product_template_attribute_value_ids.ids
        )
        self.assertEqual(code, 'WIDGET.CB')  # C(identifier)+B(blue code_value); red skipped

    def test_variant_create_generates_default_code(self):
        """Creating a variant without default_code builds it from base_code."""
        tmpl = self._make_template(
            base_code='ABC',
            attribute_line_ids=[(0, 0, {
                'attribute_id': self.attr_color.id,
                'value_ids': [(6, 0, (self.color_red + self.color_blue).ids)],
            })],
        )
        for variant in tmpl.product_variant_ids:
            self.assertTrue(variant.default_code)
            self.assertTrue(variant.default_code.startswith('ABC'))

    def test_variant_change_on_create_sets_dimension(self):
        """An attribute with change_on_create sets the matching dimension on the
        variant, and weight is recomputed for a dimension-based weight_kind."""
        self.attr_size.change_on_create = 'length'
        self.size_l.value_on_create = 3.0
        tmpl = self._make_template(
            weight_kind='length',
            weight_factor=2.0,
            attribute_line_ids=[(0, 0, {
                'attribute_id': self.attr_size.id,
                'value_ids': [(6, 0, (self.size_s + self.size_l).ids)],
            })],
        )
        ptav_l = tmpl.attribute_line_ids.product_template_value_ids.filtered(
            lambda v: v.product_attribute_value_id == self.size_l
        )
        variant = tmpl._create_product_variant(ptav_l)
        self.assertTrue(variant)
        self.assertAlmostEqual(variant.product_length, 3.0)
        self.assertAlmostEqual(variant.variant_weight, 6.0)  # factor 2.0 * length 3.0

    def test_name_search_by_base_code(self):
        """name_search matches templates by base_code."""
        self._make_template(base_code='ZZZ', name='Zeta')
        found = self.env['product.template'].name_search('ZZZ')
        self.assertTrue(found)

    def test_ptav_code_value_related(self):
        """product.template.attribute.value.code_value is related from the value."""
        tmpl = self._make_template(
            attribute_line_ids=[(0, 0, {
                'attribute_id': self.attr_color.id,
                'value_ids': [(6, 0, self.color_red.ids)],
            })],
        )
        ptav = tmpl.attribute_line_ids.product_template_value_ids[:1]
        self.assertEqual(ptav.code_value, self.color_red.code_value)
