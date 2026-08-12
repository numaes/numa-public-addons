import logging
from typing import List

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    _inherit = 'product.category'

    product_attribute_ids = fields.Many2many('product.attribute', string='Default attributes')

    def get_default_attribute_lines(self):
        self.ensure_one()

        attributes = self.product_attribute_ids
        if self.parent_id:
            attributes |= self.parent_id.get_default_attribute_lines()

        return attributes


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    base_code = fields.Char('Base code')

    def name_get(self):
        res = []
        for product in self:
            if product.base_code:
                res.append((product.id, '[%s] %s' % (product.base_code, product.name)))
            else:
                res.append((product.id, '%s' % product.name))

        return res

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        name_args = [
            '|',
            ('base_code', operator, name),
            ('name', operator, name),
        ]
        return self.search(
            name_args + (args or []),
            limit=limit
        ).name_get()

    @api.model_create_multi
    def create(self, vals_list: list):
        ptal_model = self.env['product.template.attribute.line']

        if not isinstance(vals_list, type([])):
            vals_list = [vals_list]

        products = super().create(vals_list)

        for product in products:
            attributes = product.categ_id.get_default_attribute_lines()
            for attribute in attributes:
                product.attribute_line_ids = [(4, ptal_model.create({
                    'product_tmpl_id': product.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(6, 0, attribute.value_ids.ids)],
                }).id)]

        return products

    def write(self, vals):
        ptal_model = self.env['product.template.attribute.line']

        if 'categ_id' in vals and 'attribute_line_ids' not in vals:
            for product in self:
                super(ProductTemplate, product).write(vals)
                attributes = product.categ_id.get_default_attribute_lines()
                for attribute in attributes:
                    product.attribute_line_ids = [(4, ptal_model.create({
                        'product_tmpl_id': product.id,
                        'attribute_id': attribute.id,
                        'value_ids': [(6, 0, attribute.value_ids.ids)],
                    }).id)]
        else:
            super().write(vals)

    @api.model
    def default_get(self, fields_list):
        return super().default_get(fields_list)

    def build_default_code(self, attribute_values: List):
        self.ensure_one()
        attribute_value_model = self.env['product.template.attribute.value']

        atv_ids = []
        for element in attribute_values:
            if isinstance(element, tuple) and element[0] == 4:
                atv_ids.append(element[1])
            elif isinstance(element, int):
                atv_ids.append(element)

        avs = attribute_value_model.browse(atv_ids)

        default_code = self.base_code or ''
        if avs:
            suffix = ''
            for av in avs:
                if not av.attribute_id.default_value or \
                   av.product_attribute_value_id != av.attribute_id.default_value:
                    suffix += '%s%s' % (
                        av.attribute_id.code_identifier or '',
                        av.product_attribute_value_id.code_value
                    )
            if suffix and default_code:
                default_code += '.' + suffix

        return default_code


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list: dict):
        template_model = self.env['product.template']

        if not isinstance(vals_list, type([])):
            vals_list = [vals_list]

        for vals in vals_list:
            if 'default_code' not in vals and 'product_tmpl_id' in vals:
                template = template_model.browse(vals['product_tmpl_id'])
                commands = vals.get('product_template_attribute_value_ids')
                ptav_ids = []
                for command in commands:
                    if command[0] == 4:
                        ptav_ids.append(command[1])
                    elif command[0] == 6:
                        ptav_ids.extend(command[2])

                vals['default_code'] = template.build_default_code(ptav_ids)

        new_variants = super().create(vals_list)
        new_variants._apply_attribute_dimensions()

        return new_variants

    def write(self, vals):
        """Re-apply the attribute effects when the combination changes.

        A variant does not only get its values at creation time. Adding a value
        to an attribute line that already has variants makes Odoo attach the
        new template attribute value to them, and materialising an open value
        does exactly that. Without this, such a variant would keep the
        ``default_code`` and the dimensions it had under its previous
        combination.
        """
        res = super().write(vals)
        if 'product_template_attribute_value_ids' in vals:
            self._rebuild_default_code()
            self._apply_attribute_dimensions()
        return res

    def _rebuild_default_code(self):
        """Recompose ``default_code`` from the current combination.

        ``default_code`` is entirely derived in this module — the template form
        even hides it in favour of ``base_code`` — so recomposing it when the
        combination changes is consistent rather than destructive.
        """
        for variant in self:
            template = variant.product_tmpl_id
            if not template.base_code:
                continue
            code = template.build_default_code(
                variant.product_template_attribute_value_ids.ids)
            if code and code != variant.default_code:
                variant.default_code = code

    def _apply_attribute_dimensions(self):
        """Apply the ``change_on_create`` dimensions carried by the values.

        A free numeric attribute feeds ``value_on_create``, so an arbitrary cut
        length reaches the variant dimension through the mechanism this module
        already had.
        """
        for variant in self:
            for ptav in variant.product_template_attribute_value_ids:
                change_on_create = ptav.attribute_id.change_on_create
                if not change_on_create:
                    continue
                att_value = ptav.product_attribute_value_id
                if att_value.value_on_create:
                    variant['variant_' + change_on_create] = \
                        att_value.value_on_create
                    variant.onchange_variant_weight()
                    variant.onchange_variant_dimensions()

    # === REFERENCE RESOLUTION API === #
    #
    # The surface downstream modules consume. Deliberately small and stable:
    # it answers "what material is this made of" and "which base variants are
    # compatible", and stops there. Choosing among the candidates is a
    # bill-of-materials decision, not a property of the product.

    def get_attribute_reference(self, attribute):
        """Record referenced by this variant's value of ``attribute``.

        Returns an empty recordset when the attribute is not a reference
        attribute or carries no reference.
        """
        self.ensure_one()
        ptav = self.product_template_attribute_value_ids.filtered(
            lambda value: value.attribute_id == attribute)
        if not ptav:
            return self.env['product.template'].browse()
        return ptav[0]._get_effective_reference()

    def get_attribute_references(self, model=None):
        """Every reference carried by this variant, keyed by attribute.

        ``model`` restricts the result to references of that model.
        """
        self.ensure_one()
        result = {}
        for ptav in self.product_template_attribute_value_ids:
            if ptav.attribute_id.value_type != 'reference':
                continue
            target = ptav._get_effective_reference()
            if not target:
                continue
            if model and target._name != model:
                continue
            result[ptav.attribute_id] = target
        return result

    def find_matching_variants(self, base_template):
        """Variants of ``base_template`` sharing this variant's attribute values.

        Attributes present on the base template but absent here — strip
        length, sheet size — are left unconstrained, so this returns a
        candidate set rather than a single variant. Pure mechanism: it returns
        candidates, it does not choose.
        """
        self.ensure_one()
        own_values = self.product_template_attribute_value_ids.mapped(
            'product_attribute_value_id')
        shared_attributes = base_template.attribute_line_ids.attribute_id & \
            self.product_template_attribute_value_ids.attribute_id

        candidates = base_template.product_variant_ids
        for attribute in shared_attributes:
            expected = own_values.filtered(
                lambda value: value.attribute_id == attribute)
            if not expected:
                continue
            candidates = candidates.filtered(
                lambda variant: expected <= variant
                .product_template_attribute_value_ids
                .mapped('product_attribute_value_id'))
        return candidates

    @api.onchange('weight_kind', 'weight_factor', 'surface', 'product_width',
                  'product_height', 'product_length', 'volume')
    def onchange_variant_weight(self):
        for p in self:
            weight = 0.0
            if p.weight_kind == 'length':
                weight = p.weight_factor * p.product_length
            elif p.weight_kind == 'width':
                weight = p.weight_factor * p.product_width
            elif p.weight_kind == 'height':
                weight = p.weight_factor * p.product_height
            elif p.weight_kind == 'surface':
                weight = p.weight_factor * p.surface
            elif p.weight_kind == 'volume':
                weight = p.weight_factor * p.volume

            for ptav in p.product_template_attribute_value_ids:
                weight *= ptav.product_attribute_value_id.weight_factor

            p.variant_weight = weight
