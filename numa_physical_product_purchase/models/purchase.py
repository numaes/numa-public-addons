from odoo import fields, models, api

import logging
_logger = logging.getLogger(__name__)

UNIT_PER_TYPE = {
    'length': 'm',
    'width': 'm',
    'height': 'm',
    'surface': 'm²',
    'volume': 'm³',
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
                po.po_weight += line.total_weight
                po.po_volume += line.total_volume


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface', related='product_id.surface', readonly=True)
    unit_weight = fields.Float(string='Unit Weight', related='product_id.weight', readonly=True)
    unit_volume = fields.Float(string='Unit Volume', related='product_id.volume', readonly=True)

    total_surface = fields.Float(string='Total Surface')
    total_weight = fields.Float(string='Total Weight')
    total_volume = fields.Float(string='Total Volume')

    price_qty = fields.Float(string='Price Qty')
    unit_price_uom_id = fields.Many2one('uom.uom', 'Price UoM')

    @api.onchange('product_id')
    def onchange_product_id(self):
        for pol in self:
            super(PurchaseOrderLine, pol).onchange_product_id()
            pol._compute_unit_price_uom()
            pol.compute_totals()

    @api.onchange('product_uom', 'product_uom_qty')
    def _onchange_quantity(self):
        for pol in self:
            #super(PurchaseOrderLine, pol)._onchange_quantity()
            pol._compute_unit_price_uom()
            pol.compute_totals()

    def _compute_unit_price_uom(self):
        uom_model = self.env['uom.uom']

        for pol in self:
            if pol.product_id:
                if pol.product_id.price_base == 'normal':
                    pol.unit_price_uom_id = pol.product_id.uom_id
                else:
                    pol.unit_price_uom_id = uom_model.search(
                        [('name', '=', UNIT_PER_TYPE[pol.product_id.price_base])],
                        limit=1
                    )
            else:
                pol.unit_price_uom_id = False

    @api.onchange('product_uom_qty', 'product_uom')
    @api.depends('product_uom_qty', 'product_uom')
    def compute_totals(self):
        for pol in self:
            normalized_qty = pol.product_uom._compute_quantity(pol.product_uom_qty, pol.product_id.uom_id) \
                if pol.product_uom else pol.product_uom_qty
            pol.total_surface = normalized_qty * pol.unit_surface
            pol.total_weight = normalized_qty * pol.unit_weight
            pol.total_volume = normalized_qty * pol.unit_volume

            pol.compute_price()

    @api.onchange('total_surface', 'total_weight', 'total_volume', 'product_uom_qty', 'product_uom')
    @api.depends('total_surface', 'total_weight', 'total_volume', 'product_uom_qty', 'product_uom')
    def compute_price(self):
        for pol in self:
            normalized_qty = pol.product_uom._compute_quantity(pol.product_uom_qty, pol.product_id.uom_id) \
                             if pol.product_uom else pol.product_uom_qty
            price_type = pol.product_id.price_base
            if price_type == 'length':
                price_qty = pol.unit_length * normalized_qty
            elif price_type == 'width':
                price_qty = pol.unit_width * normalized_qty
            elif price_type == 'height':
                price_qty = pol.unit_height * normalized_qty
            elif price_type == 'surface':
                price_qty = pol.total_surface
            elif price_type == 'weight':
                price_qty = pol.total_weight
            elif price_type == 'volume':
                price_qty = pol.total_volume
            else:
                price_qty = normalized_qty
            pol.price_qty = price_qty

            pol._compute_amount()

    @api.depends('price_qty', 'price_unit', 'taxes_id')
    def _compute_amount(self):
        for pol in self:
            vals = pol._prepare_compute_all_values()
            taxes = pol.taxes_id.compute_all(
                pol.price_unit,
                vals['currency_id'],
                pol.price_qty,
                vals['product'],
                vals['partner'])
            pol.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })
