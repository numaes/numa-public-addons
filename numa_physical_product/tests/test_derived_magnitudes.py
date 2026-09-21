from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'numa_physical_product')
class TestDerivedMagnitudes(TransactionCase):
    """Surface, volume and weight must be derived on every write path.

    They used to be produced only by ``@api.onchange``, so a product created
    or written through the ORM — an import, a data file, or a configured
    variant — kept a surface of zero and was costed at zero per square metre.
    """

    def _template(self, **vals):
        base = {'name': 'Phys', 'type': 'consu'}
        base.update(vals)
        return self.env['product.template'].create(base)

    # --- template -------------------------------------------------------

    def test_surface_is_derived_on_create(self):
        tmpl = self._template(product_length=3.0, product_width=2.0)
        self.assertEqual(tmpl.surface, 6.0)

    def test_volume_is_derived_on_create(self):
        tmpl = self._template(product_length=3.0, product_width=2.0,
                              product_height=0.5)
        self.assertEqual(tmpl.volume, 3.0)

    def test_surface_is_rederived_on_write(self):
        tmpl = self._template(product_length=3.0, product_width=2.0)
        tmpl.write({'product_length': 4.0})
        self.assertEqual(tmpl.surface, 8.0)

    def test_explicit_surface_wins_over_derivation(self):
        tmpl = self._template(product_length=3.0, product_width=2.0,
                              surface=99.0)
        self.assertEqual(tmpl.surface, 99.0)

    def test_weight_is_derived_from_surface_on_create(self):
        tmpl = self._template(product_length=3.0, product_width=2.0,
                              weight_kind='surface', weight_factor=2.0)
        self.assertEqual(tmpl.weight, 12.0)

    def test_normal_weight_kind_keeps_an_explicit_weight(self):
        tmpl = self._template(product_length=3.0, product_width=2.0,
                              weight_kind='normal', weight=7.0)
        self.assertEqual(tmpl.weight, 7.0)
        tmpl.write({'product_length': 4.0})
        self.assertEqual(tmpl.weight, 7.0)

    def test_untouched_dimensions_do_not_rederive(self):
        """Writing something unrelated must not recompute the magnitudes."""
        tmpl = self._template(product_length=3.0, product_width=2.0)
        tmpl.write({'surface': 42.0})
        tmpl.write({'name': 'Renamed'})
        self.assertEqual(tmpl.surface, 42.0)

    # --- variant --------------------------------------------------------

    def test_variant_surface_is_derived_on_write(self):
        tmpl = self._template()
        variant = tmpl.product_variant_id
        variant.write({'variant_length': 3.0, 'variant_width': 2.0})
        self.assertEqual(variant.surface, 6.0)

    def test_variant_volume_is_derived_on_write(self):
        tmpl = self._template()
        variant = tmpl.product_variant_id
        variant.write({'variant_length': 3.0, 'variant_width': 2.0,
                       'variant_height': 0.5})
        self.assertEqual(variant.volume, 3.0)

    def test_variant_inherits_template_surface(self):
        tmpl = self._template(product_length=3.0, product_width=2.0)
        self.assertEqual(tmpl.product_variant_id.surface, 6.0)

    def test_variant_weight_is_derived_on_write(self):
        tmpl = self._template(weight_kind='surface', weight_factor=2.0)
        variant = tmpl.product_variant_id
        variant.write({'variant_length': 3.0, 'variant_width': 2.0})
        self.assertEqual(variant.weight, 12.0)

    def test_price_qty_by_surface_after_orm_create(self):
        """The failure this whole fix exists for: a sheet costed at zero."""
        tmpl = self._template(product_length=3.0, product_width=2.0,
                              price_base='surface')
        self.assertEqual(tmpl.product_variant_id._get_price_qty(2.0), 12.0)

    def test_hand_entered_surface_survives_without_dimensions(self):
        """Nothing is derived from dimensions that are not there."""
        tmpl = self._template(surface=42.0, weight_kind='surface',
                              weight_factor=2.0)
        tmpl.write({'weight_factor': 3.0})
        self.assertEqual(tmpl.surface, 42.0)

    def test_no_weight_is_derived_from_a_zero_magnitude(self):
        tmpl = self._template(product_width=2.0, weight_kind='surface',
                              weight_factor=1.5, weight=7.0)
        self.assertEqual(tmpl.surface, 0.0)
        self.assertEqual(tmpl.weight, 7.0)


@tagged('post_install', '-at_install', 'numa_physical_product')
class TestVariantOverrides(TransactionCase):
    """A variant states its own magnitude through a flag, not through a zero.

    Zero used to mean "inherit from the template", so a variant of a template
    six metres long could not be a variant of no length at all.
    """

    def setUp(self):
        super().setUp()
        self.tmpl = self.env['product.template'].create({
            'name': 'Bar', 'type': 'consu',
            'product_length': 6.0, 'product_width': 0.04,
        })
        self.variant = self.tmpl.product_variant_id

    def test_a_genuine_zero_is_expressible(self):
        self.variant.write({'variant_length': 0.0,
                            'variant_length_set': True})
        self.assertEqual(self.variant.product_length, 0.0)
        self.assertEqual(self.tmpl.product_length, 6.0)

    def test_writing_a_magnitude_states_it(self):
        self.variant.product_length = 2.0
        self.assertTrue(self.variant.variant_length_set)
        self.assertEqual(self.variant.product_length, 2.0)

    def test_writing_the_raw_column_states_it(self):
        """``change_on_create`` writes the column, not the computed field."""
        self.variant.write({'variant_length': 2.0})
        self.assertTrue(self.variant.variant_length_set)
        self.assertEqual(self.variant.product_length, 2.0)

    def test_dropping_the_flag_inherits_again(self):
        self.variant.product_length = 2.0
        self.variant.write({'variant_length_set': False})
        self.assertEqual(self.variant.product_length, 6.0)

    def test_dropping_every_dimension_drops_the_derived_surface(self):
        """Otherwise the variant keeps the surface it derived while it had one."""
        self.variant.product_length = 2.0
        self.assertEqual(self.variant.surface, 0.08)
        self.variant.write({'variant_length_set': False})
        self.assertFalse(self.variant.variant_surface_set)
        self.assertEqual(self.variant.surface, self.tmpl.surface)

    def test_a_stated_zero_survives_a_template_change(self):
        self.variant.write({'variant_length': 0.0,
                            'variant_length_set': True})
        self.tmpl.write({'product_length': 8.0})
        self.assertEqual(self.variant.product_length, 0.0)


@tagged('post_install', '-at_install', 'numa_physical_product')
class TestStoredMagnitudes(TransactionCase):
    """Weight and volume must remain columns.

    They were unstored computes until 20.0, and that stopped being possible: three core
    reports read them straight from SQL -- `sale.report._select_dict` sums
    `product_id.weight`, and so do `purchase.report` and `pos_sale`. A report is a SQL
    view, and a field with no column cannot appear in one.

    What it looked like: installing this module before `sale` made `sale`'s own install
    fail with "Cannot convert product.product.weight to SQL because it is not stored".
    Installing it after `sale` looked fine and left a database whose sales report would
    break the next time the view was rebuilt.
    """

    def test_weight_and_volume_are_stored(self):
        fields_ = self.env['product.product']._fields
        self.assertTrue(fields_['weight'].store,
                        "product.product.weight must be a column: sale.report sums it in SQL")
        self.assertTrue(fields_['volume'].store,
                        "product.product.volume must be a column: sale.report sums it in SQL")

    def test_the_columns_are_really_there(self):
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'product_product' AND column_name IN ('weight', 'volume')
        """)
        self.assertEqual(sorted(r[0] for r in self.env.cr.fetchall()), ['volume', 'weight'])

    def test_the_stored_value_follows_the_variant_override(self):
        """Storing must not cost the override: the column holds the effective value."""
        tmpl = self.env['product.template'].create({
            'name': 'Stored', 'type': 'consu', 'weight': 10.0})
        variant = tmpl.product_variant_ids[0]
        self.assertEqual(variant.weight, 10.0)

        variant.write({'variant_weight': 4.0, 'variant_weight_set': True})
        self.assertEqual(variant.weight, 4.0)
        # A stored compute reaches the column on flush, and the SQL below reads the
        # column rather than the cache -- which is the whole point of this test.
        self.env.flush_all()
        self.env.cr.execute("SELECT weight FROM product_product WHERE id = %s", (variant.id,))
        self.assertAlmostEqual(self.env.cr.fetchone()[0], 4.0, places=3,
                               msg="the column did not follow the override")

    def test_a_sales_report_can_be_built(self):
        """The failure was not hypothetical: `sale.report` is a SQL view over these
        columns, so if they are not there the view cannot be created."""
        if 'sale.report' not in self.env:
            self.skipTest("sale is not installed on this database")
        self.env['sale.report'].search([], limit=1)
