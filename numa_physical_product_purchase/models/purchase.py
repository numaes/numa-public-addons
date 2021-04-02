from odoo import fields, models, api

import logging
_logger = logging.getLogger(__name__)

UNIT_PER_TYPE = {
    'length': 'm',
    'width': 'm',
    'height': 'm',
    'surface': 'm2',
    'volume': 'm3',
    'weight': 'kg',
}

FIELD_NAME_PER_TYPE = {
    'length': 'product_length',
    'width': 'product_width',
    'height': 'product_height',
    'surface': 'surface',
    'volume': 'volume',
    'weight': 'weight',
}


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    po_weight = fields.Float('Weight', compute='_compute_weight_volume')
    po_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.depends('order_line')
    def _compute_weight_volume(self):
        for po in self:
            po.po_weight = 0.0
            po.po_volume = 0.0
            for line in po.order_line:
                po.po_weight += line.product_uom_qty * line.product_id.weight
                po.po_volume += line.product_uom_qty * line.product_id.volume


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    product_width_rel = fields.Float(string='Width', related='product_id.product_width', readonly=True)
    product_length_rel = fields.Float(string='Length', related='product_id.product_length', readonly=True)
    product_height_rel = fields.Float(string='Height', related='product_id.product_height', readonly=True)
    product_surface_rel = fields.Float(string='Surface', related='product_id.surface', readonly=True)
    product_weight_rel = fields.Float(string='Weight', related='product_id.weight', readonly=True)
    product_volume_rel = fields.Float(string='Volume', related='product_id.volume', readonly=True)

    unit_price_display = fields.Char(string='Unit price', compute='_compute_unit_price_display')

    def _compute_unit_price_display(self):
        for sol in self:
            product = sol.product_id
            sol.unit_price_display = ('%%.%df %s/%s' % (
                sol.order_id.currency_id.decimal_places,
                sol.order_id.currency_id.symbol,
                product.uom_id.name if product and product.type in ('product', 'consu') else
                UNIT_PER_TYPE[product.price_base]) %
                sol.price_unit)

    def _prepare_compute_all_values(self):
        # Hook method to returns the different argument values for the
        # compute_all method, due to the fact that discounts mechanism
        # is not implemented yet on the purchase orders.
        # This method should disappear as soon as this feature is
        # also introduced like in the sales module.
        self.ensure_one()

        retvalue = super(PurchaseOrderLine, self)._prepare_compute_all_values()

        line = self
        if line.product_id.type in ('product', 'consu') and line.product_id.price_base != 'normal':
            unit_price = line.product_id[FIELD_NAME_PER_TYPE[line.product_id.price_base]] * line.price_unit
        else:
            unit_price = line.price_unit
        retvalue['price_unit'] = unit_price
        return retvalue
