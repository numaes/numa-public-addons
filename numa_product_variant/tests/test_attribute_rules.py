from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestAttributeRules(NumaVariantCommon):
    """Configuration rules beyond Odoo's pairwise exclusions.

    Odoo can only say "this value forbids that one". A real rule is n-ary and
    can also require rather than exclude — an object dependency in SAP terms.
    """

    def setUp(self):
        super().setUp()
        self.template = self._make_template(base_code='RULE')
        self.env['product.template.attribute.line'].create([
            {'product_tmpl_id': self.template.id,
             'attribute_id': self.attr_color.id,
             'value_ids': [(6, 0, (self.color_red + self.color_blue).ids)]},
            {'product_tmpl_id': self.template.id,
             'attribute_id': self.attr_alloy.id,
             'value_ids': [(6, 0, self.alloy_6063.ids)]},
        ])

    def _rule(self, **vals):
        values = {'name': 'rule', 'effect': 'exclude'}
        values.update(vals)
        return self.env['product.attribute.rule'].create(values)

    def _combination(self, *values):
        ptavs = self.template.attribute_line_ids.product_template_value_ids
        result = ptavs.browse()
        for value in values:
            result |= ptavs.filtered(
                lambda ptav: ptav.product_attribute_value_id == value)
        return result

    def test_combination_without_rules_is_possible(self):
        combination = self._combination(self.color_red, self.alloy_6063)
        self.assertTrue(self.template._is_combination_possible(combination))

    def test_exclude_rule_rejects_the_combination(self):
        self._rule(
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='exclude',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)])
        combination = self._combination(self.color_red, self.alloy_6063)
        self.assertFalse(self.template._is_combination_possible(combination))

    def test_exclude_rule_allows_other_combinations(self):
        self._rule(
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='exclude',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)])
        combination = self._combination(self.color_blue, self.alloy_6063)
        self.assertTrue(self.template._is_combination_possible(combination))

    def test_require_rule_rejects_a_missing_value(self):
        self._rule(
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='require',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)])
        combination = self._combination(self.color_red)
        self.assertFalse(self.template._is_combination_possible(combination))

    def test_require_rule_accepts_a_present_value(self):
        self._rule(
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='require',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)])
        combination = self._combination(self.color_red, self.alloy_6063)
        self.assertTrue(self.template._is_combination_possible(combination))

    def test_condition_is_conjunctive(self):
        """Every condition value must be present for the rule to apply — this
        is what Odoo's pairwise exclusions cannot express."""
        self._rule(
            condition_value_ids=[(6, 0, (self.color_red + self.alloy_6063).ids)],
            effect='exclude',
            effect_value_ids=[(6, 0, self.size_s.ids)])
        # Red alone does not trigger it.
        self.assertFalse(
            self.env['product.attribute.rule'].search([])._violated_by(
                self.color_red + self.size_s))
        # Red and the alloy together do.
        self.assertTrue(
            self.env['product.attribute.rule'].search([])._violated_by(
                self.color_red + self.alloy_6063 + self.size_s))

    def test_rule_is_scoped_to_its_template(self):
        other = self._make_template(base_code='OTHER')
        self._rule(
            product_tmpl_id=other.id,
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='exclude',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)])
        combination = self._combination(self.color_red, self.alloy_6063)
        self.assertTrue(self.template._is_combination_possible(combination))

    def test_global_rule_applies_to_every_template(self):
        self._rule(
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='exclude',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)])
        combination = self._combination(self.color_red, self.alloy_6063)
        self.assertFalse(self.template._is_combination_possible(combination))

    def test_creating_a_violating_variant_raises_with_the_message(self):
        """_is_combination_possible only answers yes or no, and a direct
        create never asks. The rule's own message must reach the user."""
        self._rule(
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='exclude',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)],
            message='Red is not available in alloy 6063.')
        combination = self._combination(self.color_red, self.alloy_6063)
        with self.assertRaises(ValidationError) as caught:
            self.env['product.product'].create({
                'product_tmpl_id': self.template.id,
                'product_template_attribute_value_ids': [(6, 0, combination.ids)],
            })
        self.assertIn('Red is not available in alloy 6063.', str(caught.exception))

    def test_rule_cannot_have_a_value_on_both_sides(self):
        with self.assertRaises(ValidationError):
            self._rule(
                condition_value_ids=[(6, 0, self.color_red.ids)],
                effect='exclude',
                effect_value_ids=[(6, 0, self.color_red.ids)])

    def test_archived_rule_is_ignored(self):
        rule = self._rule(
            condition_value_ids=[(6, 0, self.color_red.ids)],
            effect='exclude',
            effect_value_ids=[(6, 0, self.alloy_6063.ids)])
        rule.active = False
        combination = self._combination(self.color_red, self.alloy_6063)
        self.assertTrue(self.template._is_combination_possible(combination))
