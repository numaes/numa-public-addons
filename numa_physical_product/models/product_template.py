# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    price_base = fields.Selection(selection=[('normal', 'Normal, per product UoM'),
                                             ('length', 'Based on length [m]'),
                                             ('width', 'Based on width [m]'),
                                             ('height', 'Based on height [m]'),
                                             ('weight', 'Based on weight [kg]'),
                                             ('surface', 'Based on surface [m2]'),
                                             ('volume', 'Based on volume [m3]')],
                                  string='Base of Price',
                                  default='normal',
                                  required=True)
    weight_kind = fields.Selection(selection=[('normal', 'Normal'),
                                              ('length', 'Length based'),
                                              ('width', 'Width based'),
                                              ('height', 'Height based'),
                                              ('surface', 'Surface based'),
                                              ('volume', 'Volume based')],
                                   string='Product weight computation',
                                   required=True,
                                   default='normal',
                                   help="It computes weight automatically based on length, width, surface, volume, etc")
    weight_factor = fields.Float(string='Weight per unit [kg/unit]',
                                 digits='Stock Weight',
                                 help="Weight factor to apply")
    product_width = fields.Float(string='Width [m]', digits='Stock Length')
    product_height = fields.Float(string='Height [m]', digits='Stock Length')
    product_length = fields.Float(string='Length [m]', digits='Stock Length')
    surface = fields.Float(string='Surface [m2]', digits='Stock Surface')

    @api.onchange('product_width', 'product_height', 'product_length')
    def _onchange_dimensions(self):
        self.surface = self.product_length * self.product_width
        self.volume = self.product_length * self.product_width * self.product_height

    @api.onchange('weight_kind', 'surface', 'product_width', 'product_height', 'product_length', 'volume')
    def _onchange_weight(self):
        if self.weight_kind == 'length':
            self.weight = self.weight_factor * self.product_length
        elif self.weight_kind == 'width':
            self.weight = self.weight_factor * self.product_width
        elif self.weight_kind == 'height':
            self.weight = self.weight_factor * self.product_height
        elif self.weight_kind == 'surface':
            self.weight = self.weight_factor * self.surface
        elif self.weight_kind == 'volume':
            self.weight = self.weight_factor * self.volume
