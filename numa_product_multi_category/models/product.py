from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = "product.template"

    extended_categories = fields.Many2many('product.category',
                                           'product_extended_category_rel', 'product_id', 'category_id',
                                           'Additional Categories')

