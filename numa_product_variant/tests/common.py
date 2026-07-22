from odoo.tests.common import TransactionCase


class NumaVariantCommon(TransactionCase):
    """Shared fixtures for numa_product_variant tests.

    Builds one 'always' attribute (creates variants) and one 'dynamic' attribute
    (variants created on demand), plus a product category carrying default
    attributes, mirroring how numa_product_variant is meant to be used.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Attribute = cls.env['product.attribute']
        Value = cls.env['product.attribute.value']

        cls.attr_color = Attribute.create({
            'name': 'Color',
            'create_variant': 'always',
            'code_identifier': 'C',
        })
        cls.color_red = Value.create({
            'name': 'Red', 'attribute_id': cls.attr_color.id, 'code_value': 'R',
        })
        cls.color_blue = Value.create({
            'name': 'Blue', 'attribute_id': cls.attr_color.id, 'code_value': 'B',
        })

        cls.attr_size = Attribute.create({
            'name': 'Size',
            'create_variant': 'dynamic',
            'code_identifier': 'S',
        })
        cls.size_s = Value.create({
            'name': 'S', 'attribute_id': cls.attr_size.id, 'code_value': 'S',
        })
        cls.size_l = Value.create({
            'name': 'L', 'attribute_id': cls.attr_size.id, 'code_value': 'L',
        })

        cls.category = cls.env['product.category'].create({
            'name': 'NUMA Test Category',
            'product_attribute_ids': [(6, 0, (cls.attr_color + cls.attr_size).ids)],
        })

    def _make_template(self, **overrides):
        """Create a minimal valid product.template.

        numa_physical_product requires weight_kind + price_base (both default to
        'normal'); they are set explicitly for clarity.
        """
        vals = {
            'name': 'Test Product',
            'type': 'consu',
            'purchase_ok': True,
            'sale_ok': True,
            'weight_kind': 'normal',
            'price_base': 'normal',
            'base_code': 'TP',
        }
        vals.update(overrides)
        return self.env['product.template'].create(vals)
