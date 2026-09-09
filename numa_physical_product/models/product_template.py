# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'numa.physical.magnitudes']

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

    # ------------------------------------------------------------------
    # Derived magnitudes.  See ``numa.physical.magnitudes`` for the contract.
    # ------------------------------------------------------------------

    def _physical_triggers(self):
        return ('product_length', 'product_width', 'product_height',
                'surface', 'volume', 'weight_kind', 'weight_factor')

    def _physical_derived_vals(self, stated=()):
        self.ensure_one()
        if not (self.product_length or self.product_width or
                self.product_height):
            # Nothing is derived from dimensions that are not there, so a
            # surface entered by hand on a product that carries no dimensions
            # survives every unrelated edit.
            return {}
        derived = {}
        if 'surface' not in stated:
            derived['surface'] = self.product_length * self.product_width
        if 'volume' not in stated:
            derived['volume'] = (self.product_length * self.product_width *
                                 self.product_height)
        if 'weight' not in stated:
            weight = self._physical_weight(
                derived.get('surface', self.surface),
                derived.get('volume', self.volume))
            if weight is not None:
                derived['weight'] = weight
        return derived

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        for template, vals in zip(templates, vals_list):
            template._apply_physical_derivation(stated=vals.keys())
        return templates

    def write(self, vals):
        res = super().write(vals)
        if self._physical_derivation_needed(vals):
            self._apply_physical_derivation(stated=vals.keys())
            # A variant with dimensions of its own derives from a mix of both
            # levels, so a template dimension moving invalidates it too.
            self.product_variant_ids._apply_physical_derivation()
        return res

    @api.onchange('product_width', 'product_height', 'product_length',
                  'weight_kind', 'weight_factor')
    def _onchange_physical_dimensions(self):
        """Show in the form exactly what a write would store."""
        for name, value in self._physical_derived_vals().items():
            self[name] = value
