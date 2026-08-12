from odoo import api, models, _
from odoo.exceptions import ValidationError


class ProductTemplateAttributeLine(models.Model):
    _inherit = 'product.template.attribute.line'

    @api.constrains('active', 'value_ids', 'attribute_id')
    def _check_valid_values(self):
        """Allow an empty value list when the attribute accepts open values.

        Core requires at least one predefined value per line, because a line
        with none would make the template unconfigurable. That reasoning does
        not hold for an attribute whose values are entered freely or picked
        from a live catalogue: its list legitimately starts empty and fills up
        as values are materialised.
        """
        open_lines = self.filtered(
            lambda line: line.attribute_id.allow_additional_values
            and not line.value_ids)
        return super(ProductTemplateAttributeLine, self - open_lines)\
            ._check_valid_values()

    def _get_or_create_ptav(self, payload):
        """Return the template attribute value for a payload.

        Materialises the attribute value when needed and adds it to this line,
        which is the precondition for Odoo to build the dynamic variant. The
        whole configurator speaks in template attribute value ids, so handing
        one back keeps combination update, exclusions, pricing and variant
        creation completely untouched.
        """
        self.ensure_one()
        return self._ensure_ptav(self.attribute_id._get_or_create_value(payload))

    def _ensure_ptav(self, value):
        """Return the template attribute value for an existing attribute value.

        Adds the value to this line when missing and reactivates an archived
        template value. Use this rather than ``_get_or_create_ptav`` when the
        value already exists — a hand-curated value carries no
        ``canonical_key``, so it cannot be looked up from a payload.
        """
        self.ensure_one()
        if value.attribute_id != self.attribute_id:
            raise ValidationError(_(
                "Value %(value)s belongs to attribute %(value_attribute)s, "
                "not to %(line_attribute)s.",
                value=value.display_name,
                value_attribute=value.attribute_id.display_name,
                line_attribute=self.attribute_id.display_name))
        if value not in self.value_ids:
            self.write({'value_ids': [(4, value.id)]})
        ptav = self.product_template_value_ids.filtered(
            lambda candidate: candidate.product_attribute_value_id == value)
        if not ptav:
            self._update_product_template_attribute_values()
            ptav = self.product_template_value_ids.filtered(
                lambda candidate: candidate.product_attribute_value_id == value)
        if ptav and not ptav.ptav_active:
            ptav.write({'ptav_active': True})
        return ptav
