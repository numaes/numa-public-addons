from typing import List

from odoo import models, fields, api

import logging
_logger = logging.getLogger(__name__)


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    code_identifier = fields.Char('Code Identifier')
    default_value = fields.Many2one('product.attribute.value',
                                    domain="[('id', 'in', value_ids)]")


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    code_value = fields.Char('Code Value', required=True)


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
            res.append((product.id, '[%s] %s' % (product.base_code, product.name)))

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

        default_code = self.base_code
        if avs:
            suffix = ''
            for av in avs:
                if not(av.attribute_id.default_value) or \
                   av.product_attribute_value_id != av.attribute_id.default_value:
                    suffix += '%s%s' % (
                        av.attribute_id.code_identifier or '',
                        av.product_attribute_value_id.code_value
                    )
            if suffix:
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

        return super().create(vals_list)
