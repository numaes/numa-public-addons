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


class Invoice(models.Model):
    _inherit = 'account.move'

    invoice_weight = fields.Float('Weight', compute='_compute_weight_volume')
    invoice_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.depends('line_ids')
    def _compute_weight_volume(self):
        for invoice in self.filtered(lambda move: move.is_invoice()):
            invoice.invoice_weight = 0.0
            invoice.invoice_volume = 0.0
            for line in invoice.invoice_line_ids:
                invoice.invoice_weight += line.total_weight
                invoice.invoice_volume += line.total_volume


class InvoiceLine(models.Model):
    _inherit = 'account.move.line'

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
    def product_id_change(self):
        for il in self:
            il.compute_unit_price_uom()
            il.compute_totals()

    @api.onchange('product_uom_id', 'quantity')
    def product_uom_id_change(self):
        for il in self:
            product = il.product_id
            il.compute_unit_price_uom()
            il.compute_totals()

    def compute_unit_price_uom(self):
        uom_model = self.env['uom.uom']

        for il in self:
            if il.product_id:
                if il.product_id.price_base == 'normal':
                    il.unit_price_uom_id = il.product_id.uom_id
                else:
                    il.unit_price_uom_id = uom_model.search(
                        [('name', '=', UNIT_PER_TYPE[il.product_id.price_base])],
                        limit=1
                    )
            else:
                il.unit_price_uom_id = False

    @api.onchange('quantity', 'product_uom_id')
    @api.depends('quantity', 'product_uom_id')
    def compute_totals(self):
        for il in self:
            normalized_qty = il.product_uom_id._compute_quantity(il.quantity, il.product_id.uom_id) \
                if il.product_uom_id else il.quantity
            il.total_surface = normalized_qty * il.unit_surface
            il.total_weight = normalized_qty * il.unit_weight
            il.total_volume = normalized_qty * il.unit_volume

            il.compute_price()

    @api.onchange('total_surface', 'total_weight', 'total_volume', 'quantity', 'product_uom_id')
    @api.depends('total_surface', 'total_weight', 'total_volume', 'quantity', 'product_uom_id')
    def compute_price(self):
        for il in self:
            normalized_qty = il.product_uom_id._compute_quantity(il.quantity, il.product_id.uom_id) \
                             if il.product_uom_id else il.quantity
            price_type = il.product_id.price_base
            if price_type == 'length':
                price_qty = il.unit_length * normalized_qty
            elif price_type == 'width':
                price_qty = il.unit_width * normalized_qty
            elif price_type == 'height':
                price_qty = il.unit_height * normalized_qty
            elif price_type == 'surface':
                price_qty = il.total_surface
            elif price_type == 'weight':
                price_qty = il.total_weight
            elif price_type == 'volume':
                price_qty = il.total_volume
            else:
                price_qty = normalized_qty
            il.price_qty = price_qty
            il.flush()

            il._compute_amount()

    @api.depends('price_qty', 'price_unit', 'tax_ids')
    def _compute_amount(self):
        for il in self:
            taxes = il.tax_ids.compute_all(il.price_unit, il.move_id.currency_id, il.price_qty,
                                           product=il.product_id, partner=il.move_id.partner_id)
            il.update({
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })
