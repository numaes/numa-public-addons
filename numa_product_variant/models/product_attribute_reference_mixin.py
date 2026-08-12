from odoo import api, models, fields

REFERENCE_MODELS = [
    ('product.template', 'Product Template'),
    ('product.product', 'Product Variant'),
    ('product.attribute.value', 'Attribute Value'),
]


class ProductAttributeReferenceMixin(models.AbstractModel):
    """Reference payload shared by attribute values and template attribute values.

    Concrete ``Many2one`` columns rather than a bare ``fields.Reference``: the
    latter stores ``'product.product,42'`` as text, with no foreign key, no
    ``ondelete`` and no way to filter or join, so deleting a referenced record
    would leave silent dangling pointers. ``reference_record`` provides the
    uniform generic API on top of the concrete columns.

    Another module extends this by adding its own ``Many2one``, extending
    ``reference_model`` with ``selection_add`` and overriding
    ``_reference_field_map``.
    """
    _name = 'product.attribute.reference.mixin'
    _description = 'Product Attribute Reference Payload'

    reference_model = fields.Selection(
        REFERENCE_MODELS, string='Referenced Model',
        help="Which kind of record this value points at.")
    reference_template_id = fields.Many2one(
        'product.template', string='Referenced Template',
        ondelete='restrict', index='btree_not_null')
    reference_variant_id = fields.Many2one(
        'product.product', string='Referenced Variant',
        ondelete='restrict', index='btree_not_null')
    reference_value_id = fields.Many2one(
        'product.attribute.value', string='Referenced Value',
        ondelete='restrict', index='btree_not_null')

    reference_record = fields.Reference(
        REFERENCE_MODELS, string='Referenced Record',
        compute='_compute_reference_record', inverse='_inverse_reference_record',
        help="Uniform read/write access to the referenced record.")

    def _reference_field_map(self):
        """Model name -> name of the column holding its foreign key."""
        return {
            'product.template': 'reference_template_id',
            'product.product': 'reference_variant_id',
            'product.attribute.value': 'reference_value_id',
        }

    @api.depends('reference_model', 'reference_template_id',
                 'reference_variant_id', 'reference_value_id')
    def _compute_reference_record(self):
        for record in self:
            record.reference_record = record._get_reference_record() or False

    def _inverse_reference_record(self):
        for record in self:
            target = record.reference_record
            field_map = record._reference_field_map()
            values = {field: False for field in field_map.values()}
            values['reference_model'] = target._name if target else False
            if target:
                values[field_map[target._name]] = target.id
            record.write(values)

    def _get_reference_record(self):
        """Return the referenced record, or an empty recordset."""
        self.ensure_one()
        if not self.reference_model:
            return self.env['product.template'].browse()
        field_name = self._reference_field_map().get(self.reference_model)
        if not field_name:
            return self.env[self.reference_model].browse()
        return self[field_name]
