import logging

from odoo import api, models, fields, _
from odoo.exceptions import ValidationError

from .product_attribute_reference_mixin import REFERENCE_MODELS

_logger = logging.getLogger(__name__)


class ProductAttribute(models.Model):
    """Attribute declaring what kind of data its values carry.

    ``value_type`` is orthogonal to Odoo's two existing axes:

    - ``create_variant`` decides whether a value materialises a variant. It is
      the counterpart of SAP's configurable material versus material variant
      decision, and is reused unchanged.
    - ``display_type`` decides how the predefined list is rendered.

    The predefined values remain an *optional list*, not a mode: an attribute
    may have a list and still accept values outside it, which is what SAP calls
    "additional values" and what D365 models as "Text with or without a fixed
    list".
    """
    _inherit = "product.attribute"

    code_identifier = fields.Char('Code Identifier')
    default_value = fields.Many2one('product.attribute.value',
                                    domain="[('id', 'in', value_ids)]")
    change_on_create = fields.Selection(
        [('length', 'Length'), ('width', 'Width'), ('height', 'Height')],
        'Set on variant creation',
    )

    value_type = fields.Selection(
        [
            ('char', 'Text'),
            ('number', 'Number'),
            ('date', 'Date'),
            ('reference', 'Reference to a record'),
        ],
        string='Value Type', default='char', required=True,
        help="Data type of this attribute's values. Orthogonal to the display "
             "type and to variant creation.")
    reference_model = fields.Selection(
        REFERENCE_MODELS, string='Referenced Model',
        help="Model whose records this attribute's values point at.")
    reference_domain = fields.Char(
        string='Reference Domain',
        help="Optional domain restricting which records may be referenced.")
    allow_additional_values = fields.Boolean(
        string='Allow Additional Values',
        help="Allow values outside the predefined list. The list then acts as "
             "a set of suggestions rather than a closed set.")
    number_min = fields.Float(string='Minimum Value')
    number_max = fields.Float(string='Maximum Value')
    number_rounding = fields.Float(
        string='Rounding', default=0.001,
        help="Numeric values are rounded to this precision before being "
             "compared, so that 1250.0 and 1250.0000001 are the same value "
             "and therefore the same product.")
    code_format = fields.Char(
        string='Code Format', default='%(value)s',
        help="Python format string used to build the code of materialised "
             "values, e.g. '%(value)04.0f'.")

    @api.constrains('value_type', 'reference_model')
    def _check_reference_model(self):
        for attribute in self:
            if attribute.value_type == 'reference' and not attribute.reference_model:
                raise ValidationError(_(
                    "Attribute %(name)s references records, so it must declare "
                    "a referenced model.", name=attribute.display_name))

    @api.constrains('number_min', 'number_max')
    def _check_number_bounds(self):
        for attribute in self:
            if attribute.number_min and attribute.number_max and \
                    attribute.number_min > attribute.number_max:
                raise ValidationError(_(
                    "Attribute %(name)s has a minimum greater than its maximum.",
                    name=attribute.display_name))

    @api.constrains('value_type', 'number_rounding')
    def _check_number_rounding(self):
        for attribute in self:
            if attribute.value_type == 'number' and attribute.number_rounding <= 0.0:
                raise ValidationError(_(
                    "Attribute %(name)s must have a strictly positive rounding.",
                    name=attribute.display_name))
