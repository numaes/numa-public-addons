import logging
from typing import List

from odoo import models, fields, api, _, exceptions

_logger = logging.getLogger(__name__)


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    code_identifier = fields.Char('Code Identifier')
    default_value = fields.Many2one('product.attribute.value',
                                    domain="[('id', 'in', value_ids)]")
    change_on_create = fields.Selection(
        [('length', 'Length'), ('width', 'Width'), ('height', 'Height')],
        'Set on variant creation',
    )


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    code_value = fields.Char('Code Value', required=True)
    value_on_create = fields.Float('Value to set on variant creation')
    weight_factor = fields.Float('Weight factor', default=1.0)


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    code_value = fields.Char('Code Value',
                             related='product_attribute_value_id.code_value')


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

    def action_manual_variant_creation(self):
        self.ensure_one()

        if not self.attribute_line_ids:
            raise exceptions.UserError(
                _('This product has no variants!!')
            )

        if all([pa.attribute_id.create_variant == 'always' for pa in self.attribute_line_ids]):
            raise exceptions.UserError(
                _('All attributes are automatically created. Nothing left to be done!')
            )

        vals = dict(
            template_id=self.id,
        )

        for n in range(0, 10):
            if n >= len(self.attribute_line_ids):
                break
            vals[f'attribute{n}'] = self.attribute_line_ids[n].id
            vals[f'required{n}'] = self.attribute_line_ids[n].attribute_id.create_variant == 'allways'

        wizard = self.env['product.cmvariant'].create(vals)

        return {
            'name': _('Manually create variant'),
            'view_mode': 'form',
            'res_model': 'product.cmvariant',
            'res_id': wizard.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }


class CreateManualVariantWizard(models.Model):
    _name = 'product.cmvariant'
    _description = 'Create Manual Variant'

    template_id = fields.Many2one('product.template', 'Template')

    attribute0 = fields.Many2one('product.template.attribute.line', 'Attribute 0')
    value0 = fields.Many2one('product.template.attribute.value', 'Value 0')
    required0 = fields.Boolean('Required 0')

    attribute1 = fields.Many2one('product.template.attribute.line', 'Attribute 1')
    value1 = fields.Many2one('product.template.attribute.value', 'Value 1')
    required1 = fields.Boolean('Required 1')

    attribute2 = fields.Many2one('product.template.attribute.line', 'Attribute 2')
    value2 = fields.Many2one('product.template.attribute.value', 'Value 2')
    required2 = fields.Boolean('Required 2')

    attribute3 = fields.Many2one('product.template.attribute.line', 'Attribute 3')
    value3 = fields.Many2one('product.template.attribute.value', 'Value 3')
    required3 = fields.Boolean('Required 3')

    attribute4 = fields.Many2one('product.template.attribute.line', 'Attribute 4')
    value4 = fields.Many2one('product.template.attribute.value', 'Value 4')
    required4 = fields.Boolean('Required 4')

    attribute5 = fields.Many2one('product.template.attribute.line', 'Attribute 5')
    value5 = fields.Many2one('product.template.attribute.value', 'Value 5')
    required5 = fields.Boolean('Required 5')

    attribute6 = fields.Many2one('product.template.attribute.line', 'Attribute 6')
    value6 = fields.Many2one('product.template.attribute.value', 'Value 6')
    required6 = fields.Boolean('Required 6')

    attribute7 = fields.Many2one('product.template.attribute.line', 'Attribute 7')
    value7 = fields.Many2one('product.template.attribute.value', 'Value 7')
    required7 = fields.Boolean('Required 7')

    attribute8 = fields.Many2one('product.template.attribute.line', 'Attribute 8')
    value8 = fields.Many2one('product.template.attribute.value', 'Value 8')
    required8 = fields.Boolean('Required 8')

    attribute9 = fields.Many2one('product.template.attribute.line', 'Attribute 9')
    value9 = fields.Many2one('product.template.attribute.value', 'Value 9')
    required9 = fields.Boolean('Required 9')

    def action_create_new_variant(self):
        product_model = self.env['product.product']
        self.ensure_one()

        wizard = self

        attribute_value_ids = []
        if wizard.value0:
            attribute_value_ids.append(wizard.value0.id)
        if wizard.value1:
            attribute_value_ids.append(wizard.value1.id)
        if wizard.value2:
            attribute_value_ids.append(wizard.value2.id)
        if wizard.value3:
            attribute_value_ids.append(wizard.value3.id)
        if wizard.value4:
            attribute_value_ids.append(wizard.value4.id)
        if wizard.value5:
            attribute_value_ids.append(wizard.value5.id)
        if wizard.value6:
            attribute_value_ids.append(wizard.value6.id)
        if wizard.value7:
            attribute_value_ids.append(wizard.value7.id)
        if wizard.value8:
            attribute_value_ids.append(wizard.value8.id)
        if wizard.value9:
            attribute_value_ids.append(wizard.value9.id)

        product_filter = [('product_template_attribute_value_ids.id', '=', avid) for avid in attribute_value_ids]
        existing_product = product_model.search(
            [('product_tmpl_id', '=', wizard.template_id.id)] + product_filter,
            limit=1
        )
        if existing_product:
            raise exceptions.UserError(
                _('There is already a variant with this attribute values!. Please check it!')
            )

        new_product = product_model.create(dict(
            product_tmpl_id=wizard.template_id.id,
            product_template_attribute_value_ids=[(4, pav_id) for pav_id in attribute_value_ids]
        ))

        new_product.default_code = wizard.template_id.build_default_code(attribute_value_ids)

        return {
            'name': _('New variant'),
            'view_mode': 'form',
            'res_model': 'product.product',
            'res_id': new_product.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }


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

        for variant in new_variants:
            for ptav in variant.product_template_attribute_value_ids:
                if ptav.attribute_id.change_on_create:
                    att_value = ptav.product_attribute_value_id
                    if att_value.value_on_create:
                        variant['variant_' + ptav.attribute_line_id.attribute_id.change_on_create] = \
                            att_value.value_on_create

            variant.onchange_variant_dimensions()
            variant.onchange_variant_weight()

        return new_variants

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
