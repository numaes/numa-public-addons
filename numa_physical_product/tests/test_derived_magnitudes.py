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
