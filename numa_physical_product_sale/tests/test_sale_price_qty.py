"""Selling by the kilo, the metre and the cubic metre — outside the form as well."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSalePriceQty(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.partner = cls.env['res.partner'].create({'name': 'Buyer'})

    def _product(self, price_base='normal', price=3.0, **dims):
        vals = {
            'name': 'Physical %s' % price_base,
            'type': 'consu',
            'weight_kind': 'normal',
            'price_base': price_base,
            'list_price': price,
            'uom_id': self.uom_unit.id,
        }
        vals.update(dims)
        return self.env['product.template'].create(vals).product_variant_id

    def _order(self, product, qty=4.0, uom=None):
        line = {'product_id': product.id, 'product_uom_qty': qty}
        if uom:
            line['product_uom_id'] = uom.id
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, line)],
        })

    # ------------------------------------------------------------------
    # The regression
    # ------------------------------------------------------------------

    def test_01_a_line_created_in_code_is_priced_by_its_magnitude(self):
        """The four fields this module adds were filled only by `@api.onchange`.

        So they were filled only when a human typed into the form. A quotation
        template, an import, the website shop, an API call, a duplicated order — all
        of them produced a line with `price_qty` at zero, and `price_qty` is what goes
        on the tax base. Four slabs of 12.5 kg at 3.00/kg came to 12.00 rather than
        150.00: a plausible number, on the invoice, with nothing in the log.
        """
        slab = self._product('weight', price=3.0, weight=12.5)

        order = self._order(slab, qty=4.0)
        line = order.order_line

        self.assertEqual(line.total_weight, 50.0)
        self.assertEqual(line.price_qty, 50.0)
        self.assertEqual(line.price_subtotal, 150.0)

    def test_02_changing_the_quantity_moves_the_price(self):
        slab = self._product('weight', price=3.0, weight=12.5)
        order = self._order(slab, qty=4.0)

        order.order_line.product_uom_qty = 6.0

        self.assertEqual(order.order_line.price_qty, 75.0)
        self.assertEqual(order.order_line.price_subtotal, 225.0)

    # ------------------------------------------------------------------
    # Each price base
    # ------------------------------------------------------------------

    def test_03_a_normal_product_is_priced_per_unit(self):
        """The module must be invisible to everything it is not about."""
        plain = self._product('normal', price=3.0)

        line = self._order(plain, qty=4.0).order_line

        self.assertEqual(line.price_qty, 4.0)
        self.assertEqual(line.price_subtotal, 12.0)

    def test_04_length_width_and_height(self):
        for price_base, dimension, value, expected in (
            ('length', 'product_length', 2.0, 8.0),
            ('width', 'product_width', 1.5, 6.0),
            ('height', 'product_height', 0.5, 2.0),
        ):
            with self.subTest(price_base=price_base):
                product = self._product(price_base, price=3.0, **{dimension: value})

                line = self._order(product, qty=4.0).order_line

                self.assertEqual(line.price_qty, expected)
                self.assertEqual(line.price_subtotal, expected * 3.0)

    def test_05_surface_and_volume(self):
        for price_base, dimension, value, expected in (
            ('surface', 'surface', 2.5, 10.0),
            ('volume', 'volume', 0.4, 1.6),
        ):
            with self.subTest(price_base=price_base):
                product = self._product(price_base, price=3.0, **{dimension: value})

                line = self._order(product, qty=4.0).order_line

                self.assertAlmostEqual(line.price_qty, expected, places=6)

    # ------------------------------------------------------------------
    # Units of measure
    # ------------------------------------------------------------------

    def test_06_the_quantity_is_normalised_to_the_product_uom(self):
        """A dozen slabs weigh twelve slabs' worth, not one."""
        slab = self._product('weight', price=3.0, weight=12.5)

        line = self._order(slab, qty=2.0, uom=self.uom_dozen).order_line

        self.assertEqual(line.total_weight, 24 * 12.5)
        self.assertEqual(line.price_qty, 300.0)

    def test_07_the_price_uom_names_the_magnitude_not_the_product_uom(self):
        """What the customer sees a unit price against: 3.00 per kg, not per slab."""
        self.assertEqual(
            self._order(self._product('weight', weight=1.0)).order_line
                .unit_price_uom_id.name, 'kg')
        self.assertEqual(
            self._order(self._product('normal')).order_line
                .unit_price_uom_id, self.uom_unit)

    # ------------------------------------------------------------------
    # The override
    # ------------------------------------------------------------------

    def test_08_a_total_typed_over_by_hand_is_what_is_charged(self):
        """The piece on the pallet is not always the piece in the product record.

        The totals stay writable for that reason, and the price must follow the figure
        the salesperson stands behind, not the catalogue's.
        """
        slab = self._product('weight', price=3.0, weight=12.5)
        order = self._order(slab, qty=4.0)

        order.order_line.total_weight = 47.0

        self.assertEqual(order.order_line.price_qty, 47.0)
        self.assertEqual(order.order_line.price_subtotal, 141.0)

    def test_09_a_new_quantity_overrules_a_stale_override(self):
        slab = self._product('weight', price=3.0, weight=12.5)
        order = self._order(slab, qty=4.0)
        order.order_line.total_weight = 47.0

        order.order_line.product_uom_qty = 8.0

        self.assertEqual(order.order_line.total_weight, 100.0)

    # ------------------------------------------------------------------
    # The order
    # ------------------------------------------------------------------

    def test_10_the_order_adds_up_its_lines(self):
        slab = self._product('weight', price=3.0, weight=12.5, volume=0.4)
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                (0, 0, {'product_id': slab.id, 'product_uom_qty': 4.0}),
                (0, 0, {'product_id': slab.id, 'product_uom_qty': 2.0}),
            ],
        })

        self.assertEqual(order.so_weight, 75.0)
        self.assertAlmostEqual(order.so_volume, 2.4, places=6)

    def test_11_the_order_total_follows_a_line(self):
        """It depended on `order_line` alone, so editing a line left it stale."""
        slab = self._product('weight', price=3.0, weight=12.5)
        order = self._order(slab, qty=4.0)
        self.assertEqual(order.so_weight, 50.0)

        order.order_line.product_uom_qty = 8.0

        self.assertEqual(order.so_weight, 100.0)

    # ------------------------------------------------------------------
    # Taxes
    # ------------------------------------------------------------------

    def test_12_tax_is_computed_on_the_magnitude(self):
        """`_prepare_base_line_for_taxes_computation` is the supported hook for this.

        It replaced a fork of `_compute_amount` that called `compute_all` by hand --
        which in Odoo 20 would have disagreed with the rest of the document about
        rounding, discounts and down payments.
        """
        tax = self.env['account.tax'].create({
            'name': '10%', 'amount_type': 'percent', 'amount': 10.0,
            'type_tax_use': 'sale',
        })
        slab = self._product('weight', price=3.0, weight=12.5)
        order = self._order(slab, qty=4.0)
        order.order_line.tax_ids = [(6, 0, tax.ids)]

        self.assertEqual(order.order_line.price_subtotal, 150.0)
        self.assertEqual(order.order_line.price_total, 165.0)

    # ------------------------------------------------------------------
    # Invoicing
    # ------------------------------------------------------------------

    def test_13_the_invoice_line_carries_the_magnitude_over(self):
        """The invoice is billed in metres, and says so.

        A dimension-based product invoices what was ordered, scaled: nothing has to be
        delivered first for the magnitude to be known. Weight and volume are the
        exception -- they are read off the delivered moves, which is
        `_get_qty_to_invoice_weight_or_volume` and belongs to the stock bridge.
        """
        beam = self._product('length', price=3.0, product_length=2.0,
                             invoice_policy='order')
        order = self._order(beam, qty=4.0)
        order.action_confirm()

        values = order.order_line._prepare_invoice_line()

        self.assertEqual(values['quantity'], 4.0)
        self.assertEqual(values['price_qty'], 8.0)
        self.assertEqual(
            self.env['uom.uom'].browse(values['unit_price_uom_id']).name, 'm')

    def test_14_a_normal_product_invoices_its_units(self):
        plain = self._product('normal', price=3.0, invoice_policy='order')
        order = self._order(plain, qty=4.0)
        order.action_confirm()

        values = order.order_line._prepare_invoice_line()

        self.assertEqual(values['quantity'], 4.0)
        self.assertEqual(values['price_qty'], values['quantity'])
        self.assertEqual(
            self.env['uom.uom'].browse(values['unit_price_uom_id']), self.uom_unit)

    # ------------------------------------------------------------------
    # What was removed
    # ------------------------------------------------------------------

    def test_15_no_override_of_a_core_method_that_is_gone(self):
        """Three overrides here pointed at APIs core dropped in 17.0.

        `_get_real_price_currency` returned `(0.0, False)` -- zero-priced every line,
        had anything still called it. `update_prices` is `_recompute_prices` now, and
        the `show_update_pricelist` field it wrote no longer exists.
        `_get_price_total_and_subtotal_model` is an `account.move.line` method from
        Odoo 14 that was defined on a sale order line, so nothing ever called it, and
        it computed taxes through an API the 20.0 engine does not have.

        Leaving a dead override in place is how a module comes to look like it is doing
        something it stopped doing two versions ago.
        """
        line_methods = dir(self.env['sale.order.line'])
        order_methods = dir(self.env['sale.order'])

        self.assertNotIn('_get_real_price_currency', order_methods)
        self.assertNotIn('update_prices', order_methods)
        self.assertNotIn('show_update_pricelist', self.env['sale.order']._fields)
        self.assertNotIn('_get_price_total_and_subtotal_model', line_methods)
