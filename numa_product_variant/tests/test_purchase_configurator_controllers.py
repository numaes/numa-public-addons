import json

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestPurchaseConfiguratorControllers(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure a known admin password for JSON-RPC authentication.
        cls.env.ref('base.user_admin').write({'password': 'admin'})
        Attribute = cls.env['product.attribute']
        Value = cls.env['product.attribute.value']
        cls.attr_size = Attribute.create({
            'name': 'Size', 'create_variant': 'dynamic', 'code_identifier': 'S',
        })
        cls.size_s = Value.create({'name': 'S', 'attribute_id': cls.attr_size.id, 'code_value': 'S'})
        cls.size_l = Value.create({'name': 'L', 'attribute_id': cls.attr_size.id, 'code_value': 'L'})
        cls.tmpl = cls.env['product.template'].create({
            'name': 'Dynamic Panel',
            'type': 'consu', 'purchase_ok': True,
            'weight_kind': 'normal', 'price_base': 'normal', 'base_code': 'PANEL',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': cls.attr_size.id,
                'value_ids': [(6, 0, (cls.size_s + cls.size_l).ids)],
            })],
        })
        cls.ptav_s = cls.tmpl.attribute_line_ids.product_template_value_ids.filtered(
            lambda v: v.product_attribute_value_id == cls.size_s
        )

    def _jsonrpc(self, route, params):
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': params}
        resp = self.url_open(route, data=json.dumps(payload),
                             headers={'Content-Type': 'application/json'})
        body = resp.json()
        self.assertNotIn('error', body, body.get('error'))
        return body['result']

    def test_get_values_returns_zero_price(self):
        self.authenticate('admin', 'admin')
        result = self._jsonrpc('/purchase/product_configurator/get_values', {
            'product_template_id': self.tmpl.id,
            'quantity': 1,
            'currency_id': self.env.company.currency_id.id,
            'so_date': '2026-07-21 00:00:00',
        })
        self.assertTrue(result['products'])
        self.assertEqual(result['products'][0]['price'], 0.0)
        self.assertEqual(result['optional_products'], [])

    def test_create_product_creates_dynamic_variant(self):
        self.authenticate('admin', 'admin')
        before = self.env['product.product'].search_count([('product_tmpl_id', '=', self.tmpl.id)])
        product_id = self._jsonrpc('/purchase/product_configurator/create_product', {
            'product_template_id': self.tmpl.id,
            'ptav_ids': self.ptav_s.ids,
        })
        self.assertTrue(product_id)
        after = self.env['product.product'].search_count([('product_tmpl_id', '=', self.tmpl.id)])
        self.assertGreaterEqual(after, before)

    def test_update_combination_returns_zero_price(self):
        self.authenticate('admin', 'admin')
        result = self._jsonrpc('/purchase/product_configurator/update_combination', {
            'product_template_id': self.tmpl.id,
            'ptav_ids': self.ptav_s.ids,
            'currency_id': self.env.company.currency_id.id,
            'so_date': '2026-07-21 00:00:00',
            'quantity': 1,
        })
        self.assertEqual(result.get('price'), 0.0)
