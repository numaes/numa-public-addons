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


class ProductProduct(models.Model):
    _inherit = 'product.product'

    weight_factor = fields.Float(string='Weight Factor [kg/unit]',
                                 compute="get_weight_factor",
                                 inverse="set_weight_factor",
                                 digits='Stock Weight',
                                 help="The weight factor")
    weight = fields.Float(string='Weight [kg]',
                          compute="get_weight",
                          inverse="set_weight",
                          digits='Stock Weight',
                          help="The weight of the contents in Kg, not including any packaging, etc.")
    volume = fields.Float(string='Volume [m3]',
                          compute="get_volume",
                          inverse="set_volume",
                          digits='Stock Volume')
    surface = fields.Float(string='Surface [m2]',
                           compute="get_surface",
                           inverse="set_surface",
                           digits='Stock Surface')
    product_width = fields.Float(string='Width [m]',
                                 compute="get_width",
                                 inverse="set_width",
                                 digits='Stock Length')
    product_height = fields.Float(string='Height [m]',
                                  compute="get_height",
                                  inverse="set_height",
                                  digits='Stock Length')
    product_length = fields.Float(string='Length [m]',
                                  compute="get_length",
                                  inverse="set_length",
                                  digits='Stock Length')

    variant_weight_factor = fields.Float(string='Variant Weight Factor [kg/unit]')
    variant_weight = fields.Float(string='Variant Weight [kg]')
    variant_volume = fields.Float(string='Variant Volume [m3]')
    variant_surface = fields.Float(string='Variant Surface [m2]')
    variant_width = fields.Float(string='Variant Width [m]')
    variant_height = fields.Float(string='Variant Height [m]')
    variant_length = fields.Float(string='Variant Length [m]')

    def get_weight_factor(self):
        for product in self:
            product.weight_factor = product.variant_weight_factor if product.variant_weight_factor != 0 else \
                                    product.product_tmpl_id.weight_factor

    def set_weight_factor(self):
        for product in self:
            product.variant_weight_factor = product.weight_factor

    def get_weight(self):
        for product in self:
            product.weight = product.variant_weight if product.variant_weight != 0 else \
                             product.product_tmpl_id.weight

    def set_weight(self):
        for product in self:
            product.variant_weight = product.weight

    def get_volume(self):
        for product in self:
            product.volume = product.variant_volume if product.variant_volume != 0 else \
                             product.product_tmpl_id.volume

    def set_volume(self):
        for product in self:
            product.variant_volume = product.volume

    def get_surface(self):
        for product in self:
            product.surface = product.variant_surface if product.variant_surface != 0 else \
                              product.product_tmpl_id.surface

    def set_surface(self):
        for product in self:
            product.variant_surface = product.surface

    def get_length(self):
        for product in self:
            product.product_length = product.variant_length if product.variant_length != 0 else \
                                     product.product_tmpl_id.product_length

    def set_length(self):
        for product in self:
            product.variant_length = product.product_length

    def get_width(self):
        for product in self:
            product.product_width = product.variant_width if product.variant_width != 0 else \
                                    product.product_tmpl_id.product_width

    def set_width(self):
        for product in self:
            product.variant_width = product.product_width

    def get_height(self):
        for product in self:
            product.product_height = product.variant_height if product.variant_height != 0 else \
                                     product.product_tmpl_id.product_height

    def set_height(self):
        for product in self:
            product.variant_height = product.product_height

    @api.onchange('product_width', 'product_height', 'product_length')
    def onchange_variant_dimensions(self):
        self.variant_surface = self.product_length * self.product_width
        self.variant_volume = self.product_length * self.product_width * self.product_height
        self.get_volume()
        self.get_weight()
        self.get_surface()
        self._onchange_variant_weight()

    @api.onchange('weight_kind', 'weight_factor', 'surface', 'product_width',
                  'product_height', 'product_length', 'volume')
    def _onchange_variant_weight(self):
        if self.weight_kind == 'length':
            self.variant_weight = self.weight_factor * self.product_length
        elif self.weight_kind == 'width':
            self.variant_weight = self.weight_factor * self.product_width
        elif self.weight_kind == 'height':
            self.variant_weight = self.weight_factor * self.product_height
        elif self.weight_kind == 'surface':
            self.variant_weight = self.weight_factor * self.surface
        elif self.weight_kind == 'volume':
            self.variant_weight = self.weight_factor * self.volume


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    base = fields.Selection(selection_add=[('volume', 'Volume, price per m3'),
                                            ('surface', 'Surface, price per m2'),
                                            ('weight', 'Weight, price per kg'),
                                            ('length', 'Length, price per m'),
                                            ('width', 'Width, price per m'),
                                            ('height', 'Height, price per m')],
                            ondelete={'volume': 'set default',
                                      'surface': 'set default',
                                      'weight': 'set default',
                                      'length': 'set default',
                                      'width': 'set default',
                                      'height': 'set default'})
