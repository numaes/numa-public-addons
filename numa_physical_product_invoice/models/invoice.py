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

# The three price bases that also have a total on the line, which a user may type over
# when the physical piece is not what the product record says. For those, the line's
# own figure is what the price is applied to.
OVERRIDABLE_TOTAL_PER_BASE = {
    'surface': 'total_surface',
    'weight': 'total_weight',
    'volume': 'total_volume',
}


class Invoice(models.Model):
    _inherit = 'account.move'

    invoice_weight = fields.Float('Weight', compute='_compute_weight_volume')
    invoice_volume = fields.Float('Volume', compute='_compute_weight_volume')

    # It depended on `line_ids` alone, so the figures went stale the moment a line's
    # quantity moved -- the list of lines had not changed, only what was on them.
    @api.depends('invoice_line_ids.total_weight', 'invoice_line_ids.total_volume')
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
        lines = super().create(vals_list)

        physical = self.env['account.move.line']
        keep_price_qty = self.env['account.move.line']
        for line, vals in zip(lines, vals_list):
            if not line.move_id.is_invoice(include_receipts=True) or not line.product_id:
                continue
            physical |= line
            if 'price_qty' in vals:
                keep_price_qty |= line

        if physical:
            physical._sync_dimension_totals()
            # A line that arrived with its own `price_qty` keeps it. The sale order it
            # came from reads weight and volume off what the delivery actually weighed
            # -- which is the whole reason the stock bridge records them per line --
            # and recomputing here from the catalogue would bill a different figure
            # from the one that was picked, with both documents looking correct.
            (physical - keep_price_qty)._sync_price_qty()
            physical._compute_totals()
        return lines

    def write(self, vals):
        result = super().write(vals)

        if not {'quantity', 'product_id', 'product_uom_id'} & set(vals):
            return result

        physical = self.filtered(
            lambda line: line.move_id.is_invoice(include_receipts=True) and line.product_id)
        if physical:
            # Changing the quantity on an existing line used to leave `price_qty`
            # where it was, and `price_qty` is what the tax base is computed on. Only
            # the form refreshed it, through an onchange; an edit made in code, by an
            # import or by a credit note billed the previous quantity.
            physical._sync_dimension_totals()
            if 'price_qty' not in vals:
                physical._sync_price_qty()
        return result

    def _sync_dimension_totals(self):
        """The physical magnitudes this line carries, from the product and the quantity."""
        for il in self:
            normalized_qty = il._normalized_qty()
            il.total_surface = normalized_qty * il.unit_surface
            il.total_weight = normalized_qty * il.unit_weight
            il.total_volume = normalized_qty * il.unit_volume

    def _sync_price_qty(self):
        """The quantity the price is applied to.

        The six-way branch that used to be here is `product._get_price_qty`, which
        `numa_physical_product` centralises for exactly these bridges. The only thing
        that is not the product's answer is a total the user typed over.
        """
        for il in self:
            if not il.product_id or not il.product_uom_id:
                il.price_qty = il.quantity or 1.0
                continue
            total_field = OVERRIDABLE_TOTAL_PER_BASE.get(il.product_id.price_base)
            if total_field:
                il.price_qty = il[total_field]
            else:
                il.price_qty = il.product_id._get_price_qty(
                    il.quantity, uom=il.product_uom_id)

    def _normalized_qty(self):
        self.ensure_one()
        if self.product_id and self.product_uom_id:
            return self.product_uom_id._compute_quantity(
                self.quantity, self.product_id.uom_id)
        return self.quantity

    @api.onchange('product_id')
    def product_id_change(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            il.compute_unit_price_uom()
            il._sync_dimension_totals()
            il._sync_price_qty()
            il._compute_totals()

    @api.onchange('product_uom_id', 'quantity')
    def product_uom_id_change(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            if not il.product_id or not il.product_uom_id:
                continue
            il._sync_dimension_totals()
            il._sync_price_qty()
            il._compute_totals()

    @api.onchange('total_surface', 'total_weight', 'total_volume')
    def _onchange_dimension_totals(self):
        """When the user manually edits a dimension total, update price_qty accordingly."""
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True) or not il.product_id:
                continue
            total_field = OVERRIDABLE_TOTAL_PER_BASE.get(il.product_id.price_base)
            if total_field:
                il.price_qty = il[total_field]
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

    # `_get_fields_onchange_balance` and `_get_fields_onchange_balance_model`
    # were overridden here, and neither exists in Odoo any more -- they went with the
    # accounting rework several versions ago. The overrides called a `super()` that was
    # not there, so they were dead code that would have raised the day something called
    # them. The physical quantity reaches the tax computation through
    # `_prepare_product_base_line_for_taxes_computation` above, which is the hook the
    # current engine calls.
