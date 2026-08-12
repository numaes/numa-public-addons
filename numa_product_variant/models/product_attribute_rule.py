from odoo import api, models, fields, _
from odoo.exceptions import ValidationError


class ProductAttributeRule(models.Model):
    """A rule constraining which attribute values may be combined.

    Odoo only expresses **pairwise** exclusions, through ``exclude_for`` on a
    template attribute value: one value forbids another. Real configuration
    rules are rarely pairwise — "this profile system does not admit that glass
    thickness *when* the opening is larger than X" — which is what SAP calls an
    object dependency and D365 a table constraint.

    A rule states a condition (every value in ``condition_value_ids`` present
    in the configuration) and an effect:

    - ``exclude``: none of ``effect_value_ids`` may then be present;
    - ``require``: at least one of ``effect_value_ids`` must then be present.

    Rules are evaluated in ``_is_combination_possible``, so they apply
    everywhere a combination is validated: the configurator, the variant
    matrix, and direct variant creation.
    """
    _name = 'product.attribute.rule'
    _description = 'Product Attribute Rule'
    _order = 'sequence, id'

    name = fields.Char('Description', required=True)
    sequence = fields.Integer('Sequence', default=10)
    active = fields.Boolean(default=True)

    product_tmpl_id = fields.Many2one(
        'product.template', string='Product', ondelete='cascade', index=True,
        help="Leave empty to apply the rule to every product using these "
             "attribute values.")

    condition_value_ids = fields.Many2many(
        'product.attribute.value', 'product_attribute_rule_condition_rel',
        'rule_id', 'value_id', string='When all of',
        required=True,
        help="The rule applies when every one of these values is part of the "
             "configuration.")
    effect = fields.Selection(
        [('exclude', 'Exclude'), ('require', 'Require')],
        string='Effect', default='exclude', required=True)
    effect_value_ids = fields.Many2many(
        'product.attribute.value', 'product_attribute_rule_effect_rel',
        'rule_id', 'value_id', string='Then',
        required=True)
    message = fields.Char(
        'Message', translate=True,
        help="Shown when the rule rejects a configuration.")

    @api.constrains('condition_value_ids', 'effect_value_ids')
    def _check_values_are_disjoint(self):
        for rule in self:
            overlap = rule.condition_value_ids & rule.effect_value_ids
            if overlap:
                raise ValidationError(_(
                    "Rule %(name)s has %(values)s on both sides, which can "
                    "never be satisfied.",
                    name=rule.name,
                    values=', '.join(overlap.mapped('display_name'))))

    @api.model
    def _rules_for_template(self, template):
        """Rules applying to a template: its own, plus the global ones."""
        return self.search([
            '|',
            ('product_tmpl_id', '=', False),
            ('product_tmpl_id', '=', template.id),
        ])

    def _violated_by(self, values):
        """Return the rules of ``self`` that ``values`` violates.

        ``values`` is a ``product.attribute.value`` recordset — the plain
        values of a combination, not the template-specific ones, so a rule
        written once applies to every template sharing those attributes.
        """
        violated = self.browse()
        for rule in self:
            if not (rule.condition_value_ids <= values):
                continue
            present = rule.effect_value_ids & values
            if rule.effect == 'exclude' and present:
                violated |= rule
            elif rule.effect == 'require' and not present:
                violated |= rule
        return violated

    def _violation_message(self):
        """Human-readable reason why these rules rejected a configuration."""
        return '\n'.join(
            rule.message or _(
                "%(condition)s %(effect)s %(values)s.",
                condition=', '.join(rule.condition_value_ids.mapped('display_name')),
                effect=(_('cannot be combined with') if rule.effect == 'exclude'
                        else _('requires one of')),
                values=', '.join(rule.effect_value_ids.mapped('display_name')),
            )
            for rule in self
        )
