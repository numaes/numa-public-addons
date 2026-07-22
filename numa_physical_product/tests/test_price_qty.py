from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'numa_physical_product')
class TestGetPriceQty(TransactionCase):
    """Unit tests for product.product._get_price_qty (price_base scaling)."""

    def _variant(self, price_base='normal', **dims):
        vals = {
            'name': 'Phys Product',
            'type': 'consu',
            'weight_kind': 'normal',
            'price_base': price_base,
        }
        vals.update(dims)
        return self.env['product.template'].create(vals).product_variant_id

    def test_normal_returns_quantity(self):
        p = self._variant('normal')
        self.assertEqual(p._get_price_qty(3.0), 3.0)

    def test_length(self):
        p = self._variant('length', product_length=2.0)
        self.assertEqual(p._get_price_qty(3.0), 6.0)

    def test_width(self):
        p = self._variant('width', product_width=1.5)
        self.assertEqual(p._get_price_qty(4.0), 6.0)

    def test_height(self):
        p = self._variant('height', product_height=0.5)
        self.assertEqual(p._get_price_qty(4.0), 2.0)

    def test_weight(self):
        p = self._variant('weight', weight=5.0)
        self.assertEqual(p._get_price_qty(3.0), 15.0)

    def test_surface(self):
        p = self._variant('surface', surface=4.0)
        self.assertEqual(p._get_price_qty(2.0), 8.0)

    def test_volume(self):
        p = self._variant('volume', volume=1.5)
        self.assertEqual(p._get_price_qty(2.0), 3.0)

    def test_uom_none_matches_product_uom(self):
        p = self._variant('weight', weight=2.0)
        self.assertEqual(p._get_price_qty(3.0), p._get_price_qty(3.0, p.uom_id))
