"""Buying by the kilo, the metre and the cubic metre — outside the form as well."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPurchasePriceQty(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.vendor = cls.env['res.partner'].create({'name': 'Vendor'})

    def _product(self, price_base='normal', **dims):
        vals = {
            'name': 'Physical %s' % price_base,
            'type': 'consu',
            'weight_kind': 'normal',
            'price_base': price_base,
            'standard_price': 3.0,
            'uom_id': self.uom_unit.id,
        }
        vals.update(dims)
        return self.env['product.template'].create(vals).product_variant_id

    def _order(self, product, qty=4.0, uom=None):
        line = {'product_id': product.id, 'product_qty': qty, 'price_unit': 3.0}
        if uom:
            line['uom_id'] = uom.id
        return self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [(0, 0, line)],
        })

    # ------------------------------------------------------------------
    # The regression
    # ------------------------------------------------------------------

    def test_01_a_line_created_in_code_is_priced_by_its_magnitude(self):
        """On this model the onchange did not even cover the form.

        The four fields were filled by handlers keyed on `product_uom_qty` — which in
        20.0 is a computed field, while the quantity a buyer types is `product_qty`.
        So `price_qty` stayed at zero everywhere, and `price_qty` is what goes on the
        tax base: four slabs of 12.5 kg at 3.00/kg were costed at 12.00 rather than
        150.00.
        """
        slab = self._product('weight', weight=12.5)

        line = self._order(slab, qty=4.0).order_line

        self.assertEqual(line.total_weight, 50.0)
        self.assertEqual(line.price_qty, 50.0)
        self.assertEqual(line.price_subtotal, 150.0)

    def test_02_changing_the_quantity_moves_the_price(self):
        slab = self._product('weight', weight=12.5)
        order = self._order(slab, qty=4.0)

        order.order_line.product_qty = 6.0

        self.assertEqual(order.order_line.price_qty, 75.0)
        self.assertEqual(order.order_line.price_subtotal, 225.0)

    def test_03_the_quantity_is_normalised_once_not_twice(self):
        """`product_uom_qty` is already the quantity in the product's own unit.

        Core computes it as `uom_id._compute_quantity(product_qty, product.uom_id)`,
        and this module converted it again — so a line bought in dozens reported
        twelve times the weight it carried.
        """
        slab = self._product('weight', weight=12.5)

        line = self._order(slab, qty=2.0, uom=self.uom_dozen).order_line

        self.assertEqual(line.total_weight, 24 * 12.5)
        self.assertEqual(line.price_qty, 300.0)

    # ------------------------------------------------------------------
    # Each price base
    # ------------------------------------------------------------------

    def test_04_a_normal_product_is_priced_per_unit(self):
        line = self._order(self._product('normal'), qty=4.0).order_line

        self.assertEqual(line.price_qty, 4.0)
        self.assertEqual(line.price_subtotal, 12.0)

    def test_05_each_price_base(self):
        for price_base, dimension, value, expected in (
            ('length', 'product_length', 2.0, 8.0),
            ('width', 'product_width', 1.5, 6.0),
            ('height', 'product_height', 0.5, 2.0),
            ('surface', 'surface', 2.5, 10.0),
            ('volume', 'volume', 0.4, 1.6),
            ('weight', 'weight', 12.5, 50.0),
        ):
            with self.subTest(price_base=price_base):
                product = self._product(price_base, **{dimension: value})

                line = self._order(product, qty=4.0).order_line

                self.assertAlmostEqual(line.price_qty, expected, places=6)

    def test_06_the_price_uom_names_the_magnitude(self):
        self.assertEqual(
            self._order(self._product('weight', weight=1.0)).order_line
                .unit_price_uom_id.name, 'kg')
        self.assertEqual(
            self._order(self._product('normal')).order_line
                .unit_price_uom_id, self.uom_unit)

    # ------------------------------------------------------------------
    # The override
    # ------------------------------------------------------------------

    def test_07_a_total_typed_over_by_hand_is_what_is_paid(self):
        """The delivery is weighed on arrival, and that figure is what the vendor
        invoices against."""
        slab = self._product('weight', weight=12.5)
        order = self._order(slab, qty=4.0)

        order.order_line.total_weight = 47.0

        self.assertEqual(order.order_line.price_qty, 47.0)
        self.assertEqual(order.order_line.price_subtotal, 141.0)

    def test_08_a_new_quantity_overrules_a_stale_override(self):
        slab = self._product('weight', weight=12.5)
        order = self._order(slab, qty=4.0)
        order.order_line.total_weight = 47.0

        order.order_line.product_qty = 8.0

        self.assertEqual(order.order_line.total_weight, 100.0)

    # ------------------------------------------------------------------
    # The order
    # ------------------------------------------------------------------

    def test_09_the_order_adds_up_its_lines(self):
        slab = self._product('weight', weight=12.5, volume=0.4)
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [
                (0, 0, {'product_id': slab.id, 'product_qty': 4.0, 'price_unit': 3.0}),
                (0, 0, {'product_id': slab.id, 'product_qty': 2.0, 'price_unit': 3.0}),
            ],
        })

        self.assertEqual(order.po_weight, 75.0)
        self.assertAlmostEqual(order.po_volume, 2.4, places=6)

    def test_10_the_order_total_follows_a_line(self):
        """It depended on `order_line` alone, so editing a line left it stale."""
        slab = self._product('weight', weight=12.5)
        order = self._order(slab, qty=4.0)
        self.assertEqual(order.po_weight, 50.0)

        order.order_line.product_qty = 8.0

        self.assertEqual(order.po_weight, 100.0)

    def test_13_the_order_total_is_the_magnitude_total(self):
        """The order's untaxed amount follows the magnitude, a typed-over one included.

        `test_07` passed without the `price_qty` dependency on `_compute_amount` only
        because it never read the subtotal before typing over the total. Once computed,
        the subtotal stayed where it was.
        """
        slab = self._product('weight', weight=12.5)
        order = self._order(slab, qty=4.0)

        self.assertEqual(order.amount_untaxed, 150.0)

        order.order_line.total_weight = 47.0

        self.assertEqual(order.order_line.price_subtotal, 141.0)
        self.assertEqual(order.amount_untaxed, 141.0)

    # ------------------------------------------------------------------
    # Taxes
    # ------------------------------------------------------------------

    def test_11_tax_is_computed_on_the_magnitude(self):
        tax = self.env['account.tax'].create({
            'name': '10%', 'amount_type': 'percent', 'amount': 10.0,
            'type_tax_use': 'purchase',
        })
        slab = self._product('weight', weight=12.5)
        order = self._order(slab, qty=4.0)
        order.order_line.tax_ids = [(6, 0, tax.ids)]

        self.assertEqual(order.order_line.price_subtotal, 150.0)
        self.assertEqual(order.order_line.price_total, 165.0)

    # ------------------------------------------------------------------
    # What was removed
    # ------------------------------------------------------------------

    def test_12_the_vendor_price_refresh_is_not_suppressed(self):
        """`_onchange_quantity` was overridden here with its `super()` commented out.

        Core has no method of that name in 20.0, so the override sat there shadowing
        nothing — but it is exactly the shape that silently disables a core handler the
        moment core adds one back. The computations it called are computed fields now
        and the override is gone.
        """
        self.assertFalse(
            hasattr(self.env['purchase.order.line'], '_onchange_quantity'))
        self.assertFalse(
            hasattr(self.env['purchase.order.line'], 'compute_totals'))
