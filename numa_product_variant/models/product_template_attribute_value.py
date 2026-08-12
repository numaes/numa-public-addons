from odoo import models, fields


class ProductTemplateAttributeValue(models.Model):
    """Template attribute value, able to override the reference of its value.

    The mixin fields default to ``False`` here and only take effect when set,
    so a template can redirect a shared attribute value to a different record
    without affecting any other template.
    """
    _name = 'product.template.attribute.value'
    _inherit = ['product.template.attribute.value',
                'product.attribute.reference.mixin']

    code_value = fields.Char('Code Value',
                             related='product_attribute_value_id.code_value')

    def _get_effective_reference(self):
        """Referenced record for this template value.

        The template value overrides the attribute value when it sets one.
        This is the only place the precedence rule lives; consumers must go
        through it rather than reading the columns directly.
        """
        self.ensure_one()
        return self._get_reference_record() or \
            self.product_attribute_value_id._get_reference_record()

    def _get_effective_value(self):
        """Typed Python value carried by this template value."""
        self.ensure_one()
        value = self.product_attribute_value_id
        value_type = self.attribute_id.value_type
        if value_type == 'reference':
            return self._get_effective_reference()
        if value_type == 'number':
            return value.free_number
        if value_type == 'date':
            return value.free_date
        return value.name
