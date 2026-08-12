import json

from odoo.tests.common import HttpCase, tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestResolveValueControllers(HttpCase, NumaVariantCommon):
    """End-to-end materialisation through the configurator routes.

    The route hands back a template attribute value id, which is the only
    currency the rest of the configurator understands.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure a known admin password for JSON-RPC authentication.
        cls.env.ref('base.user_admin').write({'password': 'admin'})

    def setUp(self):
        super().setUp()
        self.cut = self._make_cut_piece_template()
        self.authenticate('admin', 'admin')

    def _jsonrpc(self, route, params, expect_error=False):
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': params}
        resp = self.url_open(route, data=json.dumps(payload),
                             headers={'Content-Type': 'application/json'})
        body = resp.json()
        if expect_error:
            return body
        self.assertNotIn('error', body, body.get('error'))
        return body['result']

    def _line(self, attribute):
        return self.cut.attribute_line_ids.filtered(
            lambda candidate: candidate.attribute_id == attribute)

    def test_sale_route_materializes_a_reference(self):
        line = self._line(self.attr_profile)
        result = self._jsonrpc('/sale/product_configurator/resolve_value', {
            'product_template_id': self.cut.id,
            'ptal_id': line.id,
            'payload': {'reference': ['product.template', self.profile_l4040.id]},
        })
        ptav = self.env['product.template.attribute.value'].browse(
            result['ptav_id'])
        self.assertEqual(ptav._get_effective_reference(), self.profile_l4040)
        self.assertEqual(result['code_value'], 'L4040')

    def test_purchase_route_materializes_a_number(self):
        line = self._line(self.attr_length)
        result = self._jsonrpc('/purchase/product_configurator/resolve_value', {
            'product_template_id': self.cut.id,
            'ptal_id': line.id,
            'payload': {'number': 800.0},
        })
        ptav = self.env['product.template.attribute.value'].browse(
            result['ptav_id'])
        self.assertEqual(ptav.product_attribute_value_id.free_number, 800.0)
        self.assertEqual(result['code_value'], '0800')

    def test_route_is_idempotent(self):
        line = self._line(self.attr_length)
        params = {
            'product_template_id': self.cut.id,
            'ptal_id': line.id,
            'payload': {'number': 800.0},
        }
        first = self._jsonrpc(
            '/purchase/product_configurator/resolve_value', params)
        second = self._jsonrpc(
            '/purchase/product_configurator/resolve_value', params)
        self.assertEqual(first['ptav_id'], second['ptav_id'])

    def test_line_must_belong_to_the_template(self):
        other = self._make_template(base_code='OTHER')
        foreign = self.env['product.template.attribute.line'].create({
            'product_tmpl_id': other.id, 'attribute_id': self.attr_color.id,
            'value_ids': [(6, 0, self.color_red.ids)],
        })
        body = self._jsonrpc(
            '/sale/product_configurator/resolve_value',
            {
                'product_template_id': self.cut.id,
                'ptal_id': foreign.id,
                'payload': {'char': 'x'},
            },
            expect_error=True)
        self.assertIn('error', body)

    def test_closed_attribute_is_rejected_by_the_route(self):
        """Validation is server-side, so it holds for every entry path."""
        self.attr_length.allow_additional_values = False
        line = self._line(self.attr_length)
        body = self._jsonrpc(
            '/purchase/product_configurator/resolve_value',
            {
                'product_template_id': self.cut.id,
                'ptal_id': line.id,
                'payload': {'number': 800.0},
            },
            expect_error=True)
        self.assertIn('error', body)
