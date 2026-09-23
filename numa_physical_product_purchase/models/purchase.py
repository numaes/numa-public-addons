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


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    po_weight = fields.Float('Weight', compute='_compute_weight_volume')
    po_volume = fields.Float('Volume', compute='_compute_weight_volume')

    # It depended on `order_line` alone, so the figures went stale the moment a line's
    # quantity moved -- the list of lines had not changed, only what was on them.
    @api.depends('order_line.total_weight', 'order_line.total_volume')
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

    # These four were plain stored fields, filled only by `@api.onchange` handlers --
    # so they were filled only when a human typed into the form. A purchase line
    # created any other way (an import, a replenishment rule, an API call) carried a
    # `price_qty` of zero. It did not show on the order only because nothing read
    # `price_qty` at all: the tax base was handed over through
    # `_convert_to_tax_base_line_dict`, a hook core no longer calls, so every purchase
    # was costed by the unit whatever its price base.
    total_surface = fields.Float(
        string='Total Surface', compute='_compute_physical_totals',
        store=True, readonly=False)
    total_weight = fields.Float(
        string='Total Weight', compute='_compute_physical_totals',
        store=True, readonly=False)
    total_volume = fields.Float(
        string='Total Volume', compute='_compute_physical_totals',
        store=True, readonly=False)

    price_qty = fields.Float(
        string='Price Qty', compute='_compute_price_qty', store=True,
        help="The quantity the price is applied to: the physical magnitude named by "
             "the product's price base, or the ordered quantity when it prices "
             "normally.")
    unit_price_uom_id = fields.Many2one(
        'uom.uom', 'Price UoM', compute='_compute_unit_price_uom', store=True)

    # Two onchange handlers were removed from here. `onchange_product_id` only existed
    # to call these computations by hand, and `_onchange_quantity` overrode a core
    # method of that name that no longer exists -- with its `super()` call commented
    # out, which in an earlier version would have suppressed the vendor price refresh
    # entirely.

    @api.depends('product_id', 'product_id.price_base', 'product_id.uom_id')
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

    def _normalized_qty(self):
        """The ordered quantity in the product's own unit of measure.

        Which is what `product_uom_qty` already is on this model -- core computes it
        as `uom_id._compute_quantity(product_qty, product.uom_id)`. This module
        converted it a second time, so a line bought in dozens reported twelve times
        the weight it carried.
        """
        self.ensure_one()
        return self.product_uom_qty

    @api.depends('product_uom_qty', 'product_id',
                 'unit_surface', 'unit_weight', 'unit_volume')
    def _compute_physical_totals(self):
        for pol in self:
            normalized_qty = pol._normalized_qty()
            pol.total_surface = normalized_qty * pol.unit_surface
            pol.total_weight = normalized_qty * pol.unit_weight
            pol.total_volume = normalized_qty * pol.unit_volume

    @api.depends('total_surface', 'total_weight', 'total_volume', 'product_uom_qty',
                 'product_id', 'product_id.price_base',
                 'unit_length', 'unit_width', 'unit_height')
    def _compute_price_qty(self):
        # The six-way branch that used to be here is `product._get_price_qty`, which
        # `numa_physical_product` centralises for exactly these bridges. The only thing
        # that is not the product's answer is a total the user typed over.
        for pol in self:
            if not pol.product_id:
                pol.price_qty = pol.product_uom_qty
                continue
            total_field = OVERRIDABLE_TOTAL_PER_BASE.get(pol.product_id.price_base)
            if total_field:
                pol.price_qty = pol[total_field]
            else:
                pol.price_qty = pol.product_id._get_price_qty(pol._normalized_qty())

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        """Tax the physical quantity, not the number of units.

        Was `_convert_to_tax_base_line_dict`, which Odoo removed along with the old
        tax engine. The hook is the same idea in the new one (`account_tax.py`): hand the tax computation a base line, and let core do the
        rounding, the tax details and the document-level logic. What this module changes
        is one number in that line.
        """
        values = super()._prepare_base_line_for_taxes_computation(**kwargs)
        if self.product_id.price_base != 'normal' and self.price_qty:
            values['quantity'] = self.price_qty
        return values

    @api.depends('price_qty')
    def _compute_amount(self):
        """Recompute the amounts when the physical quantity moves.

        Core's `_compute_amount` depends on `product_qty`; ours is driven by
        `price_qty`, which core has never heard of. Without this, a total typed over by
        hand changed `price_qty` and left the subtotal it had already computed where it
        was -- the line said 47 kg and charged for 50.
        """
        return super()._compute_amount()