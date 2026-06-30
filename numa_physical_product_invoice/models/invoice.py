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


class Invoice(models.Model):
    _inherit = 'account.move'

    invoice_weight = fields.Float('Weight', compute='_compute_weight_volume')
    invoice_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.depends('line_ids')
    def _compute_weight_volume(self):
        for invoice in self:
            if invoice.is_invoice():
                invoice.invoice_weight = 0.0
                invoice.invoice_volume = 0.0
                for line in invoice.invoice_line_ids:
                    invoice.invoice_weight += line.total_weight
                    invoice.invoice_volume += line.total_volume
            else:
                invoice.invoice_weight = 0.0
                invoice.invoice_volume = 0.0

    def _prepare_product_base_line_for_taxes_computation(self, product_line):
        result = super()._prepare_product_base_line_for_taxes_computation(product_line)
        if (
            self.is_invoice(include_receipts=True)
            and product_line.price_qty is not False
            and abs((product_line.price_qty or 0.0) - product_line.quantity) > 0.0001
        ):
            result['quantity'] = product_line.price_qty
        return result


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

    price_qty = fields.Float(string='Price Qty', default=1.0)
    unit_price_uom_id = fields.Many2one('uom.uom', 'Price UoM')
    price_base = fields.Selection(related='product_id.price_base', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        mls = super().create(vals_list)
        to_sync = mls.filtered(
            lambda l: l.move_id.is_invoice(include_receipts=True) and l.product_id
        )
        if to_sync:
            to_sync._sync_price_qty()
            to_sync._compute_totals()
        return mls

    def _sync_price_qty(self):
        """Compute price_qty and dimension totals from product dimensions and quantity.
        Called on programmatic creation (SO/PO invoicing, credit notes) and from onchange handlers.
        """
        for il in self:
            if not il.product_id or not il.product_uom_id:
                il.price_qty = il.quantity or 1.0
                continue

            normalized_qty = il.product_uom_id._compute_quantity(il.quantity, il.product_id.uom_id)
            il.total_surface = normalized_qty * il.unit_surface
            il.total_weight = normalized_qty * il.unit_weight
            il.total_volume = normalized_qty * il.unit_volume

            price_type = il.product_id.price_base
            if price_type == 'length':
                il.price_qty = il.product_id.product_length * normalized_qty
            elif price_type == 'width':
                il.price_qty = il.product_id.product_width * normalized_qty
            elif price_type == 'height':
                il.price_qty = il.product_id.product_height * normalized_qty
            elif price_type == 'surface':
                il.price_qty = il.total_surface
            elif price_type == 'weight':
                il.price_qty = il.total_weight
            elif price_type == 'volume':
                il.price_qty = il.total_volume
            else:
                il.price_qty = normalized_qty

    @api.onchange('product_id')
    def product_id_change(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            il.compute_unit_price_uom()
            il._sync_price_qty()
            il._compute_totals()

    @api.onchange('product_uom_id', 'quantity')
    def product_uom_id_change(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            if not il.product_id or not il.product_uom_id:
                continue
            il._sync_price_qty()
            il._compute_totals()

    @api.onchange('total_surface', 'total_weight', 'total_volume')
    def _onchange_dimension_totals(self):
        """When the user manually edits a dimension total, update price_qty accordingly."""
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True) or not il.product_id:
                continue
            price_type = il.product_id.price_base
            if price_type == 'surface':
                il.price_qty = il.total_surface
            elif price_type == 'weight':
                il.price_qty = il.total_weight
            elif price_type == 'volume':
                il.price_qty = il.total_volume
            il._compute_totals()

    def compute_unit_price_uom(self):
        uom_model = self.env['uom.uom']

        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            if il.product_id:
                if il.product_id.price_base == 'normal':
                    il.unit_price_uom_id = il.product_id.uom_id.id
                else:
                    il.unit_price_uom_id = uom_model.search(
                        [('name', '=', UNIT_PER_TYPE[il.product_id.price_base])],
                        limit=1
                    ).id
            else:
                il.unit_price_uom_id = False

    @api.depends('price_qty')
    def _compute_totals(self):
        super()._compute_totals()

    def _get_fields_onchange_balance(self, quantity=None, discount=None, amount_currency=None, move_type=None, currency=None, taxes=None, price_subtotal=None, force_computation=False):
        self.ensure_one()
        return self._get_fields_onchange_balance_model(
            quantity=(quantity or self.quantity) if self.product_id.price_base == 'normal' else self.price_qty,
            discount=discount or self.discount,
            amount_currency=amount_currency or self.amount_currency,
            move_type=move_type or self.move_id.move_type,
            currency=currency or self.currency_id or self.move_id.currency_id,
            taxes=taxes or self.tax_ids,
            price_subtotal=price_subtotal or self.price_subtotal,
            force_computation=force_computation,
        )

    @api.model
    def _get_fields_onchange_balance_model(self, quantity, discount, amount_currency, move_type, currency, taxes,
                                           price_subtotal, force_computation=False):
        if not self or not self.product_id:
            return {}
        else:
            return super()._get_fields_onchange_balance_model(
                quantity, discount, amount_currency, move_type, currency, taxes,
                price_subtotal, force_computation=force_computation)