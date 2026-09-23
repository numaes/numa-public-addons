"""Invoicing the magnitude: the kilos that shipped, not the number of pieces."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInvoicePriceQty(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.partner = cls.env['res.partner'].create({'name': 'Customer'})

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

    def _invoice(self, product, qty=4.0, uom=None, **line_extra):
        line = {'product_id': product.id, 'quantity': qty, 'price_unit': 3.0}
        line.update(line_extra)
        if uom:
            line['product_uom_id'] = uom.id
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, line)],
        })

    def _line(self, invoice):
        return invoice.invoice_line_ids

    # ------------------------------------------------------------------
    # The magnitude
    # ------------------------------------------------------------------

    def test_01_a_line_created_in_code_is_priced_by_its_magnitude(self):
        slab = self._product('weight', weight=12.5)

        line = self._line(self._invoice(slab, qty=4.0))

        self.assertEqual(line.total_weight, 50.0)
        self.assertEqual(line.price_qty, 50.0)
        self.assertEqual(line.price_subtotal, 150.0)

    def test_02_a_normal_product_is_priced_per_unit(self):
        line = self._line(self._invoice(self._product('normal'), qty=4.0))

        self.assertEqual(line.price_qty, 4.0)
        self.assertEqual(line.price_subtotal, 12.0)

    def test_03_each_price_base(self):
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

                line = self._line(self._invoice(product, qty=4.0))

                self.assertAlmostEqual(line.price_qty, expected, places=6)

    def test_04_the_quantity_is_normalised_to_the_product_uom(self):
        slab = self._product('weight', weight=12.5)

        line = self._line(self._invoice(slab, qty=2.0, uom=self.uom_dozen))

        self.assertEqual(line.price_qty, 300.0)

    # ------------------------------------------------------------------
    # The regressions
    # ------------------------------------------------------------------

    def test_05_changing_the_quantity_reprices_the_line(self):
        """`create` synced the line and `write` did not.

        Only the form refreshed `price_qty` after that, through an onchange. An edit
        made in code, by an import or while building a credit note left the previous
        quantity in the field the tax base is computed on -- so the invoice showed one
        quantity and charged for another.
        """
        slab = self._product('weight', weight=12.5)
        invoice = self._invoice(slab, qty=4.0)
        line = self._line(invoice)
        self.assertEqual(line.price_qty, 50.0)

        line.quantity = 6.0

        self.assertEqual(line.total_weight, 75.0)
        self.assertEqual(line.price_qty, 75.0)
        self.assertEqual(line.price_subtotal, 225.0)

    def test_06_a_price_qty_handed_in_is_not_recomputed(self):
        """What shipped is not what the catalogue says, and the invoice must follow it.

        A sale order line prices weight and volume off the delivered moves' actual
        figures -- which is the whole reason the stock bridge records them per line --
        and passes the result to `_prepare_invoice_line`. `create` recomputed it from
        the catalogue and discarded that, so the customer was billed for a nominal
        weight while the delivery note said another.
        """
        slab = self._product('weight', weight=12.5)

        invoice = self._invoice(slab, qty=4.0, price_qty=47.0)

        self.assertEqual(self._line(invoice).price_qty, 47.0)
        self.assertEqual(self._line(invoice).price_subtotal, 141.0)

    def test_07_the_invoice_total_follows_its_lines(self):
        """It depended on `line_ids` alone, so a quantity change left it stale: the
        list of lines had not changed, only what was on them."""
        slab = self._product('weight', weight=12.5, volume=0.4)
        invoice = self._invoice(slab, qty=4.0)
        self.assertEqual(invoice.invoice_weight, 50.0)

        self._line(invoice).quantity = 8.0

        self.assertEqual(invoice.invoice_weight, 100.0)

    # ------------------------------------------------------------------
    # Overrides and taxes
    # ------------------------------------------------------------------

    def test_08_a_total_typed_over_by_hand_is_what_is_charged(self):
        slab = self._product('weight', weight=12.5)
        invoice = self._invoice(slab, qty=4.0)
        line = self._line(invoice)

        line.total_weight = 47.0
        line._onchange_dimension_totals()

        self.assertEqual(line.price_qty, 47.0)

    def test_09_tax_is_computed_on_the_magnitude(self):
        tax = self.env['account.tax'].create({
            'name': '10%', 'amount_type': 'percent', 'amount': 10.0,
            'type_tax_use': 'sale',
        })
        slab = self._product('weight', weight=12.5)
        invoice = self._invoice(slab, qty=4.0)
        self._line(invoice).tax_ids = [(6, 0, tax.ids)]

        self.assertEqual(self._line(invoice).price_subtotal, 150.0)
        self.assertEqual(self._line(invoice).price_total, 165.0)

    def test_10_the_price_uom_names_the_magnitude(self):
        invoice = self._invoice(self._product('weight', weight=12.5), qty=4.0)
        line = self._line(invoice)

        line.compute_unit_price_uom()

        self.assertEqual(line.unit_price_uom_id.name, 'kg')

    # ------------------------------------------------------------------
    # Lines that are not products
    # ------------------------------------------------------------------

    def test_11_a_section_line_is_left_alone(self):
        slab = self._product('weight', weight=12.5)
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [
                (0, 0, {'display_type': 'line_section', 'name': 'Slabs'}),
                (0, 0, {'product_id': slab.id, 'quantity': 4.0, 'price_unit': 3.0}),
            ],
        })

        self.assertEqual(invoice.invoice_weight, 50.0)

    def test_12_the_accounting_entries_are_not_touched(self):
        """`is_invoice` guards every hook here: a journal entry has no magnitudes."""
        entry = self.env['account.move'].create({'move_type': 'entry'})

        self.assertEqual(entry.invoice_weight, 0.0)
        self.assertEqual(entry.invoice_volume, 0.0)

    # ------------------------------------------------------------------
    # What was removed
    # ------------------------------------------------------------------

    def test_13_no_override_of_an_accounting_api_that_is_gone(self):
        """`_get_fields_onchange_balance` and `_get_fields_onchange_balance_model`
        were overridden here and went with the accounting rework several versions ago.
        Both called a `super()` that was not there."""
        methods = dir(self.env['account.move.line'])

        self.assertNotIn('_get_fields_onchange_balance', methods)
        self.assertNotIn('_get_fields_onchange_balance_model', methods)
