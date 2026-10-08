"""What a delivery actually weighed, recorded on the delivery."""

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStockPhysicals(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.customers = cls.env.ref('stock.stock_location_customers')

    def _product(self, **dims):
        vals = {
            'name': 'Slab',
            'type': 'consu',
            'is_storable': True,
            'weight_kind': 'normal',
            'weight': 10.0,
            'volume': 0.5,
            'surface': 2.0,
            'uom_id': self.uom_unit.id,
        }
        vals.update(dims)
        return self.env['product.template'].create(vals).product_variant_id

    def _move(self, product, qty=3.0):
        return self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'location_id': self.stock.id,
            'location_dest_id': self.customers.id,
        })

    def _line(self, move, qty=3.0, uom=None):
        vals = {
            'move_id': move.id,
            'product_id': move.product_id.id,
            'quantity': qty,
            'location_id': self.stock.id,
            'location_dest_id': self.customers.id,
        }
        if move.picking_id:
            # `stock.move.line.picking_id` is its own field, not a related one.
            vals['picking_id'] = move.picking_id.id
        if uom:
            vals['uom_id'] = uom.id
        return self.env['stock.move.line'].create(vals)

    def _picking(self):
        return self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_out').id,
            'location_id': self.stock.id,
            'location_dest_id': self.customers.id,
        })

    # ------------------------------------------------------------------
    # The regressions
    # ------------------------------------------------------------------

    def test_01_a_move_line_can_be_created_at_all(self):
        """`stock.move.line.product_uom_id` is `uom_id` in 20.0.

        The old name was read from a method this module's `create` override called on
        every line, so it raised `AttributeError` before any stock could move.
        Confirming a sale order died here, inside `_action_assign`, with a message
        naming a field nobody had heard of. Nothing in this module worked, and neither
        did anything downstream of a delivery.
        """
        product = self._product()
        line = self._line(self._move(product))

        self.assertEqual(line.unit_weight, 10.0)
        self.assertEqual(line.total_weight, 30.0)

    def test_02_a_dimension_entered_on_the_line_survives(self):
        """The three unit fields were non-stored related fields, and were written to.

        A write to a non-stored related field lands in the cache and nowhere else: it
        read back correctly inside the transaction and was the product's figure again
        the moment the cache was dropped. Everything this module exists to record --
        what the pallet actually weighed, what the previous delivery of the same order
        weighed -- was discarded without a word.
        """
        product = self._product()
        line = self._line(self._move(product))

        line.unit_weight = 11.0
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(line.unit_weight, 11.0)
        self.assertEqual(line.total_weight, 33.0)

    def test_03_the_catalogue_is_not_edited_from_a_delivery(self):
        """And the other half of the same bug: a related write would have gone up.

        A per-line correction must not rewrite what every other order is priced from.
        """
        product = self._product()
        line = self._line(self._move(product))

        line.unit_weight = 11.0
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(product.weight, 10.0)

    # ------------------------------------------------------------------
    # The line
    # ------------------------------------------------------------------

    def test_04_the_line_opens_at_the_catalogue_figures(self):
        product = self._product(weight=10.0, surface=2.0, volume=0.5)
        line = self._line(self._move(product))

        self.assertEqual(
            (line.unit_weight, line.unit_surface, line.unit_volume),
            (10.0, 2.0, 0.5))

    def test_05_the_totals_are_the_unit_times_the_quantity(self):
        line = self._line(self._move(self._product()), qty=3.0)

        self.assertEqual(line.total_weight, 30.0)
        self.assertEqual(line.total_surface, 6.0)
        self.assertEqual(line.total_volume, 1.5)

    def test_06_a_new_quantity_moves_the_totals(self):
        """They were plain fields kept up to date by `create` and `write` overrides
        that only fired on two specific keys; every other path left them stale."""
        line = self._line(self._move(self._product()), qty=3.0)

        line.quantity = 5.0
        self.env.flush_all()

        self.assertEqual(line.total_weight, 50.0)

    def test_07_a_total_entered_by_hand_sets_the_unit(self):
        """The operator weighs the pallet, not the piece."""
        line = self._line(self._move(self._product()), qty=3.0)

        line.total_weight = 36.0
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(line.unit_weight, 12.0)
        self.assertEqual(line.total_weight, 36.0)

    def test_08_a_total_on_nothing_is_nothing(self):
        """Dividing by the quantity is how the unit is derived; there may be none."""
        line = self._line(self._move(self._product()), qty=0.0)

        line.total_weight = 36.0
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(line.total_weight, 0.0)

    def test_09_the_quantity_is_normalised_to_the_product_uom(self):
        product = self._product(weight=10.0)
        move = self._move(product, qty=2.0)

        line = self._line(move, qty=2.0, uom=self.uom_dozen)

        self.assertEqual(line.total_weight, 24 * 10.0)

    # ------------------------------------------------------------------
    # The move and the picking
    # ------------------------------------------------------------------

    def test_10_a_move_adds_up_its_lines(self):
        move = self._move(self._product(), qty=5.0)
        move.move_line_ids.unlink()
        self._line(move, qty=3.0)
        self._line(move, qty=2.0)
        self.env.flush_all()

        self.assertEqual(move.total_weight, 50.0)
        self.assertEqual(move.total_volume, 2.5)

    def test_11_a_move_follows_a_correction_on_one_of_its_lines(self):
        move = self._move(self._product(), qty=3.0)
        line = self._line(move, qty=3.0)
        self.assertEqual(move.total_weight, 30.0)

        line.total_weight = 36.0
        self.env.flush_all()

        self.assertEqual(move.total_weight, 36.0)

    def test_12_a_move_without_lines_falls_back_to_the_product(self):
        """Before anything is reserved there are no lines, and the figure still has
        to mean something: it is what the move is expected to carry."""
        move = self._move(self._product(), qty=4.0)
        move.quantity = 4.0
        move.move_line_ids.unlink()
        self.env.flush_all()

        self.assertFalse(move.move_line_ids)
        self.assertEqual(move.total_weight, 40.0)

    def test_13_a_picking_adds_up_its_move_lines(self):
        picking = self._picking()
        move = self.env['stock.move'].create({
            'product_id': self._product().id,
            'product_uom_qty': 3.0,
            'location_id': self.stock.id,
            'location_dest_id': self.customers.id,
            'picking_id': picking.id,
        })
        move.move_line_ids.unlink()
        self._line(move, qty=3.0)
        self.env.flush_all()

        self.assertEqual(picking.picking_weight, 30.0)
        self.assertAlmostEqual(picking.picking_volume, 1.5, places=6)

    def test_14_a_picking_follows_a_correction(self):
        """It was a compute whose `@api.depends` named `move_line_ids_without_package`,
        a field Odoo 20 removed -- which is what stopped the module installing."""
        picking = self._picking()
        move = self.env['stock.move'].create({
            'product_id': self._product().id,
            'product_uom_qty': 3.0,
            'location_id': self.stock.id,
            'location_dest_id': self.customers.id,
            'picking_id': picking.id,
        })
        move.move_line_ids.unlink()
        line = self._line(move, qty=3.0)
        self.env.flush_all()
        self.assertEqual(picking.picking_weight, 30.0)

        line.total_weight = 36.0
        self.env.flush_all()

        self.assertEqual(picking.picking_weight, 36.0)

    # ------------------------------------------------------------------
    # Carrying figures forward
    # ------------------------------------------------------------------

    def test_15_a_new_line_is_seeded_from_the_last_arrival(self):
        """A batch of slabs is not the catalogue slab.

        What the same product last weighed when it came into this location is a better
        opening figure than the product record's, and the operator corrects from there.
        """
        product = self._product(weight=10.0)
        arrival = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': 3.0,
            'location_id': self.customers.id,
            'location_dest_id': self.stock.id,
        })
        arrived = self._line(arrival, qty=3.0)
        arrived.write({'location_id': self.customers.id,
                       'location_dest_id': self.stock.id,
                       'unit_weight': 11.5,
                       'state': 'done'})
        self.env.flush_all()

        outgoing = self._move(product, qty=1.0)
        vals = outgoing._prepare_move_line_vals(quantity=1.0)

        self.assertEqual(vals['unit_weight'], 11.5)

    def test_16_with_no_previous_arrival_the_product_answers(self):
        product = self._product(weight=10.0)
        outgoing = self._move(product, qty=1.0)

        vals = outgoing._prepare_move_line_vals(quantity=1.0)

        self.assertEqual(vals['unit_weight'], 10.0)

    # ------------------------------------------------------------------
    # Serial numbers: one line per unit
    # ------------------------------------------------------------------

    def _serial_receipt(self, qty):
        product = self._product(tracking='serial')
        picking_type = self.env.ref('stock.picking_type_in')
        picking_type.use_create_lots = True
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock.id,
            'picking_type_id': picking_type.id,
        })
        return move

    def _count_lookups(self):
        """Patch the lookup on the registry class and count the searches it runs."""
        StockMove = type(self.env['stock.move'])
        original = StockMove._last_arrival_dimensions
        searches = []
        StockMoveLine = type(self.env['stock.move.line'])
        original_search = StockMoveLine.search

        def counting_lookup(move):
            def counting_search(lines, domain, *args, **kwargs):
                searches.append(domain)
                return original_search(lines, domain, *args, **kwargs)
            with patch.object(StockMoveLine, 'search', counting_search):
                return original(move)

        return patch.object(StockMove, '_last_arrival_dimensions', counting_lookup), searches

    def test_17_a_serial_receipt_looks_up_the_last_arrival_once(self):
        """Confirming 15000 serial-tracked meters timed the worker out.

        Core prepares one move line per unit, and every one of them searched every line
        the product ever had for the same answer. The answer cannot change while the
        moves are being assigned, so it is asked once.
        """
        move = self._serial_receipt(25)
        patcher, searches = self._count_lookups()

        with patcher:
            move._action_confirm()

        self.assertEqual(len(move.move_line_ids), 25)
        self.assertEqual(len(searches), 1)
        self.assertEqual(set(move.move_line_ids.mapped('unit_weight')), {10.0})

    def test_18_the_memo_does_not_outlive_the_assignment(self):
        """A line marked done afterwards is the new last arrival, and must be seen."""
        move = self._serial_receipt(3)
        move._action_confirm()

        self.assertNotIn('numa_physical_product_stock.last_arrival', self.env.cr.cache)

    def test_19_the_last_arrival_lookup_has_its_index(self):
        self.env.cr.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'stock_move_line_numa_last_arrival_index'")
        self.assertTrue(self.env.cr.rowcount)
