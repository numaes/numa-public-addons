from odoo import api, models


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
        value = self.attribute_id._get_or_create_value(payload)
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
