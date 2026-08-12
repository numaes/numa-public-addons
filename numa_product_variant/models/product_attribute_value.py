from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class ProductAttributeValue(models.Model):
    """Attribute value carrying a typed payload.

    Beyond the codes this module already added, a value can now point at a
    record (the reference payload, provided by the mixin) or hold a free
    number or date.

    ``canonical_key`` rather than ``name`` is the deduplication key: ``name``
    is ``translate=True`` and therefore a jsonb column, which can carry
    neither a unique index nor an exact match.
    """
    _name = 'product.attribute.value'
    _inherit = ['product.attribute.value', 'product.attribute.reference.mixin']

    code_value = fields.Char('Code Value', required=True)
    value_on_create = fields.Float('Value to set on variant creation')
    weight_factor = fields.Float('Weight factor', default=1.0)

    canonical_key = fields.Char(
        string='Canonical Key', index=True, copy=False,
        help="Deterministic deduplication key used when materialising values "
             "on demand.")
    is_materialized = fields.Boolean(
        string='Materialised', copy=False,
        help="Created on demand by the configurator rather than curated by "
             "hand. Only these are subject to automatic archiving.")
    free_number = fields.Float(string='Numeric Value')
    free_date = fields.Date(string='Date Value')

    def init(self):
        """Partial unique indexes backing deterministic materialisation.

        These are what make the savepoint-and-retry in ``_get_or_create_value``
        correct under concurrency: without a database-level guarantee, two
        simultaneous configurators would each create their own value.
        """
        super_init = getattr(super(), 'init', None)
        if super_init:
            super_init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                product_attribute_value_canonical_key_uniq
            ON product_attribute_value (attribute_id, canonical_key)
            WHERE canonical_key IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                product_attribute_value_reference_uniq
            ON product_attribute_value (
                attribute_id, reference_model,
                COALESCE(reference_template_id, 0),
                COALESCE(reference_variant_id, 0),
                COALESCE(reference_value_id, 0))
            WHERE reference_model IS NOT NULL
        """)

    @api.constrains('reference_model', 'reference_template_id',
                    'reference_variant_id', 'reference_value_id')
    def _check_reference_domain(self):
        for value in self:
            target = value._get_reference_record()
            if not target:
                continue
            domain = value.attribute_id.reference_domain
            if not domain:
                continue
            if not target.filtered_domain(safe_eval(domain)):
                raise ValidationError(_(
                    "%(record)s is not an allowed reference for attribute "
                    "%(attribute)s.",
                    record=target.display_name,
                    attribute=value.attribute_id.display_name))

    @api.model
    def _gc_materialized_values(self, limit=1000):
        """Archive materialised values that ended up unused.

        Never deletes, never touches hand-curated values, never touches a
        value still used by a product. Returns how many were archived.
        """
        candidates = self.with_context(active_test=False).search([
            ('is_materialized', '=', True),
            ('active', '=', True),
            ('pav_attribute_line_ids', '=', False),
        ], limit=limit)
        stale = candidates.filtered(lambda value: not value.is_used_on_products)
        if stale:
            stale.write({'active': False})
        return len(stale)

    @api.constrains('reference_value_id')
    def _check_no_reference_cycle(self):
        for value in self:
            seen = set()
            current = value
            while current:
                if current.id in seen:
                    raise ValidationError(_(
                        "Attribute value %(name)s is part of a reference cycle.",
                        name=value.display_name))
                seen.add(current.id)
                current = current.reference_value_id
