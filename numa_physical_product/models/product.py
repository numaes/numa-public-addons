from odoo import models, fields, api, _

import logging
_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    weight_kind = fields.Selection([
                                ('normal', 'Normal'),
                                ('length', 'Length based'),
                                ('width', 'Width based'),
                                ('height', 'Height based'),
                                ('surface', 'Surface based'),
                                ('volume', 'Volume based')], 
                            'Product weight computation', 
                            required=True,
                            default='normal',                            
                            help="It computes weight automatically based on length, width, surface, volume, etc")
    weight_factor = fields.Float('Weight per unit [kg/unit]', 
                                 digits='Stock Weight',
                                 help="Weight factor to apply")
    product_width = fields.Float('Width [m]', digits='Stock Length')
    product_height = fields.Float('Height [m]', digits='Stock Length')
    product_length = fields.Float('Length [m]', digits='Stock Length')
    surface = fields.Float('Surface [m2]', digits='Stock Surface')

    @api.onchange('width', 'height', 'length')
    def onchange_dimensions(self):
        self.surface = self.product_length * self.product_width
        self.volume = self.product_length * self.product_width * self.product_height

    @api.onchange('weight_kind', 'surface', 'width', 'height', 'length', 'volume')
    def onchange_weight(self):
        p = self

        if p.weight_kind == 'length':
            p.weight = p.weight_factor * p.product_length
        elif p.weight_kind == 'width':
            p.weight = p.weight_factor * p.product_width
        elif p.weight_kind == 'height':
            p.weight = p.weight_factor * p.product_height
        elif p.weight_kind == 'surface':
            p.weight = p.weight_factor * p.surface
        elif p.weight_kind == 'volume':
            p.weight = p.weight_factor * p.volume


class ProductProduct(models.Model):
    _inherit = 'product.product'

    weight_factor = fields.Float('Weight Factor [kg/unit]',
                                 compute="get_weight_factor", inverse="set_weight_factor",
                                 digits='Stock Weight',
                                 help="The weight factor")
    weight = fields.Float('Weight [kg]',
                          compute="get_weight", inverse="set_weight",
                          digits='Stock Weight',
                          help="The weight of the contents in Kg, not including any packaging, etc.")
    volume = fields.Float('Volume [m3]',
                          compute="get_volume", inverse="set_volume", digits='Stock Volume')
    surface = fields.Float('Surface [m2]',
                           compute="get_surface", inverse="set_surface", digits='Stock Surface')
    product_width = fields.Float('Width [m]', compute="get_width", inverse="set_width", digits='Stock Length')
    product_height = fields.Float('Height [m]', compute="get_height", inverse="set_height", digits='Stock Length')
    product_length = fields.Float('Length [m]', compute="get_length", inverse="set_length", digits='Stock Length')

    variant_weight_factor = fields.Float('Variant Weight Factor [kg/unit]')
    variant_weight = fields.Float('Variant Weight [kg]')
    variant_volume = fields.Float('Variant Volume [m3]')
    variant_surface = fields.Float('Variant Surface [m2]')
    variant_width = fields.Float('Variant Width [m]')
    variant_height = fields.Float('Variant Height [m]')
    variant_length = fields.Float('Variant Length [m]')

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

    @api.onchange('width', 'height', 'length')
    def onchange_variant_dimensions(self):
        self.variant_surface = self.length * self.width
        self.variant_volume = self.length * self.width * self.height
        self.get_volume()
        self.get_weight()
        self.get_surface()
        self.onchange_variant_weight()

    @api.onchange('weight_kind', 'weight_factor', 'surface', 'width', 'height', 'length', 'volume')
    def onchange_variant_weight(self):
        p = self
        
        if p.weight_kind == 'length':
            p.variant_weight = p.weight_factor * p.product_length
        elif p.weight_kind == 'width':
            p.variant_weight = p.weight_factor * p.product_width
        elif p.weight_kind == 'height':
            p.variant_weight = p.weight_factor * p.product_height
        elif p.weight_kind == 'surface':
            p.variant_weight = p.weight_factor * p.surface
        elif p.weight_kind == 'volume':
            p.variant_weight = p.weight_factor * p.volume


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    base = fields.Selection(selection_add=[
            ('volume', 'Volume, price per m3'),
            ('surface', 'Surface, price per m2'),
            ('weight', 'Weight, price per kg'),
            ('length', 'Length, price per m'),
            ('width', 'Width, price per m'),
            ('height', 'Height, price per m'),
        ],
        ondelete={
            'volume': 'set default',
            'surface': 'set default',
            'weight': 'set default',
            'length': 'set default',
            'width': 'set default',
            'height': 'set default',
        }
    )

    @api.depends('categ_id', 'product_tmpl_id', 'product_id', 'fixed_price',
                 'pricelist_id', 'percent_price', 'price_discount', 'price_surcharge')
    def _get_pricelist_item_name_price(self):
        if self.categ_id:
            self.name = _("Category: %s") % (self.categ_id.display_name)
        elif self.product_tmpl_id:
            self.name = self.product_tmpl_id.name
        elif self.product_id:
            self.name = self.product_id.display_name.replace('[%s]' % self.product_id.code, '')
        else:
            self.name = _("All Products")

