from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestOpenValueConfiguratorTour(HttpCase):
    """Drive the open-value controls in a real browser.

    Everything else about open values is covered by unit tests, which run
    server-side and prove nothing about the OWL layer. This is the only test
    that shows the control renders, takes input and produces a variant.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Attribute = cls.env['product.attribute']
        Value = cls.env['product.attribute.value']

        cls.attr_colour = Attribute.create({
            'name': 'NUMA Colour', 'create_variant': 'always',
            'code_identifier': 'C', 'display_type': 'radio',
        })
        cls.red = Value.create({
            'name': 'Red', 'attribute_id': cls.attr_colour.id, 'code_value': 'R'})
        cls.blue = Value.create({
            'name': 'Blue', 'attribute_id': cls.attr_colour.id, 'code_value': 'B'})

        cls.attr_profile = Attribute.create({
            'name': 'NUMA Profile type', 'create_variant': 'dynamic',
            'code_identifier': 'P', 'value_type': 'reference',
            'reference_model': 'product.template',
            'allow_additional_values': True,
        })
        cls.attr_length = Attribute.create({
            'name': 'NUMA Segment length', 'create_variant': 'dynamic',
            'code_identifier': 'L', 'value_type': 'number',
            'allow_additional_values': True, 'number_rounding': 1.0,
            'code_format': '%(value)04.0f',
        })

        cls.profile = cls._template('NUMA Profile L 40x40', 'NPL4040')
        cls.env['product.template.attribute.line'].create({
            'product_tmpl_id': cls.profile.id,
            'attribute_id': cls.attr_colour.id,
            'value_ids': [(6, 0, (cls.red + cls.blue).ids)],
        })

        cls.cut = cls._template('NUMA Cut piece', 'NCUT')
        cls.env['product.template.attribute.line'].create([
            {'product_tmpl_id': cls.cut.id, 'attribute_id': cls.attr_profile.id,
             'value_ids': [(6, 0, [])]},
            {'product_tmpl_id': cls.cut.id, 'attribute_id': cls.attr_colour.id,
             'value_ids': [(6, 0, (cls.red + cls.blue).ids)]},
            {'product_tmpl_id': cls.cut.id, 'attribute_id': cls.attr_length.id,
             'value_ids': [(6, 0, [])]},
        ])

        cls.env['res.partner'].create({'name': 'NUMA Tour Customer'})
        # The customer database runs in Spanish, and the shared tour helpers
        # match on English labels. Pin the language rather than translate the
        # selectors, which would make the tour unreadable and brittle.
        cls.env.ref('base.user_admin').write({
            'password': 'admin', 'lang': 'en_US'})

    @classmethod
    def _template(cls, name, base_code):
        return cls.env['product.template'].create({
            'name': name, 'type': 'consu', 'sale_ok': True,
            'purchase_ok': True, 'weight_kind': 'normal',
            'price_base': 'normal', 'base_code': base_code,
            'categ_id': cls.env.ref('product.product_category_all').id,
        })

    def test_open_value_configurator_tour(self):
        self.start_tour(
            "/odoo", 'numa_open_value_configurator_tour', login='admin')
