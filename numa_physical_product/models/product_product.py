# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

import logging

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _name = 'product.product'
    _inherit = ['product.product', 'numa.physical.magnitudes']

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

    @api.depends('variant_weight_factor', 'product_tmpl_id.weight_factor')
    def get_weight_factor(self):
        for product in self:
            product.weight_factor = product.variant_weight_factor if product.variant_weight_factor != 0 else \
                                    product.product_tmpl_id.weight_factor

    def set_weight_factor(self):
        for product in self:
            product.variant_weight_factor = product.weight_factor

    @api.depends('variant_weight', 'product_tmpl_id.weight')
    def get_weight(self):
        for product in self:
            product.weight = product.variant_weight if product.variant_weight != 0 else \
                             product.product_tmpl_id.weight

    def set_weight(self):
        for product in self:
            product.variant_weight = product.weight

    @api.depends('variant_volume', 'product_tmpl_id.volume')
    def get_volume(self):
        for product in self:
            product.volume = product.variant_volume if product.variant_volume != 0 else \
                             product.product_tmpl_id.volume

    def set_volume(self):
        for product in self:
            product.variant_volume = product.volume

    @api.depends('variant_surface', 'product_tmpl_id.surface')
    def get_surface(self):
        for product in self:
            product.surface = product.variant_surface if product.variant_surface != 0 else \
                              product.product_tmpl_id.surface

    def set_surface(self):
        for product in self:
            product.variant_surface = product.surface

    @api.depends('variant_length', 'product_tmpl_id.product_length')
    def get_length(self):
        for product in self:
            product.product_length = product.variant_length if product.variant_length != 0 else \
                                     product.product_tmpl_id.product_length

    def set_length(self):
        for product in self:
            product.variant_length = product.product_length

    @api.depends('variant_width', 'product_tmpl_id.product_width')
    def get_width(self):
        for product in self:
            product.product_width = product.variant_width if product.variant_width != 0 else \
                                    product.product_tmpl_id.product_width

    def set_width(self):
        for product in self:
            product.variant_width = product.product_width

    @api.depends('variant_height', 'product_tmpl_id.product_height')
    def get_height(self):
        for product in self:
            product.product_height = product.variant_height if product.variant_height != 0 else \
                                     product.product_tmpl_id.product_height

    def set_height(self):
        for product in self:
            product.variant_height = product.product_height

    # ------------------------------------------------------------------
    # Derived magnitudes.  See ``numa.physical.magnitudes`` for the contract.
    #
    # A variant derives into its own ``variant_*`` columns, from the effective
    # dimensions — its own where it has them, the template's where it has not.
    # ------------------------------------------------------------------

    def _physical_triggers(self):
        return ('variant_length', 'variant_width', 'variant_height',
                'variant_surface', 'variant_volume', 'variant_weight_factor',
                'product_length', 'product_width', 'product_height',
                'surface', 'volume', 'weight_kind', 'weight_factor')

    def _has_own_dimensions(self):
        """Whether this variant carries any dimension of its own.

        A variant with none of them inherits every magnitude from its template
        and must keep inheriting. Storing a derived surface on it would freeze
        that number the day the template's dimensions move.
        """
        self.ensure_one()
        return bool(self.variant_length or self.variant_width or
                    self.variant_height)

    def _physical_weight_multiplier(self):
        """Extra factor applied to a derived variant weight.

        One here; a module that makes an attribute value carry a weight factor
        overrides this rather than reimplementing the derivation.
        """
        return 1.0

    def _physical_derived_vals(self, stated=()):
        self.ensure_one()
        if not self._has_own_dimensions():
            return {}
        stated = set(stated)
        derived = {}
        if not stated & {'surface', 'variant_surface'}:
            derived['variant_surface'] = (self.product_length *
                                          self.product_width)
        if not stated & {'volume', 'variant_volume'}:
            derived['variant_volume'] = (self.product_length *
                                         self.product_width *
                                         self.product_height)
        if not stated & {'weight', 'variant_weight'}:
            weight = self._physical_weight(
                derived.get('variant_surface', self.surface),
                derived.get('variant_volume', self.volume))
            if weight is not None:
                derived['variant_weight'] = (weight *
                                             self._physical_weight_multiplier())
        return derived

    @api.model_create_multi
    def create(self, vals_list):
        variants = super().create(vals_list)
        for variant, vals in zip(variants, vals_list):
            variant._apply_physical_derivation(stated=vals.keys())
        return variants

    def write(self, vals):
        res = super().write(vals)
        if self._physical_derivation_needed(vals):
            self._apply_physical_derivation(stated=vals.keys())
        return res

    @api.onchange('product_width', 'product_height', 'product_length',
                  'weight_kind', 'weight_factor')
    def _onchange_physical_dimensions(self):
        """Show in the form exactly what a write would store."""
        for name, value in self._physical_derived_vals().items():
            self[name] = value

    def _get_price_qty(self, quantity, uom=None):
        """Return the costing/billing quantity for `quantity` units of this product.

        For price_base == 'normal', this is the quantity normalized to the product
        UoM. For a physical price_base, it is the product's physical magnitude
        (length/width/height in m, surface in m2, weight in kg, volume in m3)
        multiplied by the normalized quantity. Centralizes the price_qty scaling
        used by numa_physical_product_{sale,purchase,invoice} so it can be reused
        for cost computation (e.g. recursive BoM costing).
        """
        self.ensure_one()
        qty = uom._compute_quantity(quantity, self.uom_id) if uom else quantity
        magnitude = {
            'length': self.product_length,
            'width': self.product_width,
            'height': self.product_height,
            'surface': self.surface,
            'weight': self.weight,
            'volume': self.volume,
        }.get(self.price_base)
        return magnitude * qty if magnitude is not None else qty
