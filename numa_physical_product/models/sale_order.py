# -*- coding: utf-8 -*-

from odoo import fields, models, api, exceptions, _

import logging
_logger = logging.getLogger(__name__)


class PhysicalSaleOrder(models.Model):
    _inherit = 'sale.order'

    so_weight = fields.Float('Weight', compute='_compute_weight_volume')
    so_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.depends('order_line')
    def _compute_weight_volume(self):
        for so in self:
            so.so_weight = 0.0
            so.so_volume = 0.0
            for line in so.order_line:
                so.so_weight += line.product_uom_qty * line.product_id.weight
                so.so_volume += line.product_uom_qty * line.product_id.width * \
                                line.product_id.length * line.product_id.height

        return


class PhysicalSaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    product_width_rel = fields.Float(string='Width', related='product_id.width', readonly=True)
    product_length_rel = fields.Float(string='Length', related='product_id.length', readonly=True)
    product_height_rel = fields.Float(string='Height', related='product_id.height', readonly=True)
    product_surface_rel = fields.Float(string='Surface', related='product_id.surface', readonly=True)
    product_weight_rel = fields.Float(string='Weight', related='product_id.weight', readonly=True)
    product_volume_rel = fields.Float(string='Volume', related='product_id.volume', readonly=True)
