from odoo.tests.common import tagged
from .common import NumaVariantCommon


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestPurchaseConfigurator(NumaVariantCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Test Vendor'})
        # Configurable template: 2 colors (always) + dynamic size => configurable.
        cls.config_tmpl = cls.env['product.template'].create({
            'name': 'Configurable Shirt',
            'type': 'consu', 'purchase_ok': True,
            'weight_kind': 'normal', 'price_base': 'normal', 'base_code': 'SHIRT',
            'attribute_line_ids': [
                (0, 0, {'attribute_id': cls.attr_color.id,
                        'value_ids': [(6, 0, (cls.color_red + cls.color_blue).ids)]}),
                (0, 0, {'attribute_id': cls.attr_size.id,
                        'value_ids': [(6, 0, (cls.size_s + cls.size_l).ids)]}),
            ],
        })
        # Simple template: single variant, not configurable.
        cls.simple_tmpl = cls.env['product.template'].create({
            'name': 'Simple Bolt',
            'type': 'consu', 'purchase_ok': True,
            'weight_kind': 'normal', 'price_base': 'normal', 'base_code': 'BOLT',
        })

    def _new_line(self):
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id})
        return self.env['purchase.order.line'].new({'order_id': po.id})

    def test_compute_product_template_id_from_product(self):
        line = self._new_line()
        line.product_id = self.simple_tmpl.product_variant_id
        self.assertEqual(line.product_template_id, self.simple_tmpl)

    def test_search_product_template_id(self):
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id})
        pol = self.env['purchase.order.line'].create({
            'order_id': po.id,
            'product_id': self.simple_tmpl.product_variant_id.id,
            'product_qty': 1.0,
        })
        found = self.env['purchase.order.line'].search([
            ('product_template_id', '=', self.simple_tmpl.id),
            ('id', '=', pol.id),
        ])
        self.assertEqual(found, pol)

    def test_domain_is_purchase_ok(self):
        field = self.env['purchase.order.line']._fields['product_template_id']
        self.assertIn(('purchase_ok', '=', True), field.domain)

    def test_is_configurable_product_flag(self):
        cfg_line = self._new_line()
        cfg_line.product_template_id = self.config_tmpl
        self.assertTrue(cfg_line.is_configurable_product)
        simple_line = self._new_line()
        simple_line.product_template_id = self.simple_tmpl
        self.assertFalse(simple_line.is_configurable_product)

    def test_onchange_autoassigns_single_variant(self):
        """A non-configurable template auto-assigns its single variant."""
        line = self._new_line()
        line.product_template_id = self.simple_tmpl
        line._onchange_product_template_id()
        self.assertEqual(line.product_id, self.simple_tmpl.product_variant_id)

    def test_onchange_leaves_configurable_unset(self):
        """A configurable template does not auto-assign a variant (dialog path)."""
        line = self._new_line()
        line.product_template_id = self.config_tmpl
        line._onchange_product_template_id()
        self.assertFalse(line.product_id)

    def test_onchange_clears_product_when_template_unset(self):
        line = self._new_line()
        line.product_id = self.simple_tmpl.product_variant_id
        line.product_template_id = False
        line._onchange_product_template_id()
        self.assertFalse(line.product_id)

    def test_view_exposes_product_template_id(self):
        """The PO form line must render product_template_id with our widget."""
        view = self.env.ref('purchase.purchase_order_form')
        arch = self.env['purchase.order'].get_view(view.id, 'form')['arch']
        self.assertIn('product_template_id', arch)
        self.assertIn('pol_product_many2one', arch)
