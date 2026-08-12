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

        # --- Joinery fixture -------------------------------------------------
        # An extruded aluminium profile is a template varying by colour, alloy
        # and strip length. A cut piece is a separate template that shares the
        # colour attribute with it, references the profile template, and has a
        # free segment length. It deliberately has no strip-length attribute:
        # a cut piece is indifferent to which strip it comes from.
        cls.attr_alloy = Attribute.create({
            'name': 'Alloy', 'create_variant': 'always', 'code_identifier': 'A',
        })
        cls.alloy_6063 = Value.create({
            'name': '6063', 'attribute_id': cls.attr_alloy.id, 'code_value': '63',
        })

        cls.attr_strip_length = Attribute.create({
            'name': 'Strip length', 'create_variant': 'always',
            'code_identifier': 'T',
        })
        cls.strip_6m = Value.create({
            'name': '6 m', 'attribute_id': cls.attr_strip_length.id,
            'code_value': '6',
        })
        cls.strip_45m = Value.create({
            'name': '4.5 m', 'attribute_id': cls.attr_strip_length.id,
            'code_value': '45',
        })

        cls.attr_profile = Attribute.create({
            'name': 'Profile type', 'create_variant': 'dynamic',
            'code_identifier': 'P', 'value_type': 'reference',
            'reference_model': 'product.template',
            'allow_additional_values': True,
        })
        cls.attr_length = Attribute.create({
            'name': 'Segment length', 'create_variant': 'dynamic',
            'code_identifier': 'L', 'value_type': 'number',
            'allow_additional_values': True, 'number_rounding': 1.0,
            'code_format': '%(value)04.0f',
            'change_on_create': 'length',
        })
        cls.attr_legend = Attribute.create({
            'name': 'Engraved legend', 'create_variant': 'no_variant',
            'code_identifier': 'G', 'value_type': 'char',
            'allow_additional_values': True,
        })

        cls.profile_l4040 = cls._make_profile_template('Profile L 40x40', 'L4040')

    @classmethod
    def _make_profile_template(cls, name, base_code):
        """An extruded profile: colour + alloy + strip length, all 'always'.

        `categ_id` is set explicitly to the base category so the fixture's own
        `cls.category` default attributes are not injected on top.
        """
        template = cls.env['product.template'].create({
            'name': name, 'type': 'consu', 'purchase_ok': True,
            'weight_kind': 'normal', 'price_base': 'normal',
            'base_code': base_code,
            'categ_id': cls.env.ref('product.product_category_all').id,
        })
        cls.env['product.template.attribute.line'].create([
            {'product_tmpl_id': template.id, 'attribute_id': cls.attr_color.id,
             'value_ids': [(6, 0, (cls.color_red + cls.color_blue).ids)]},
            {'product_tmpl_id': template.id, 'attribute_id': cls.attr_alloy.id,
             'value_ids': [(6, 0, cls.alloy_6063.ids)]},
            {'product_tmpl_id': template.id,
             'attribute_id': cls.attr_strip_length.id,
             'value_ids': [(6, 0, (cls.strip_6m + cls.strip_45m).ids)]},
        ])
        return template

    def _make_cut_piece_template(self):
        """A cut piece: profile reference + colour + free segment length."""
        template = self.env['product.template'].create({
            'name': 'Aluminium cut piece', 'type': 'consu',
            'purchase_ok': True, 'weight_kind': 'normal',
            'price_base': 'normal', 'base_code': 'CUT',
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        self.env['product.template.attribute.line'].create([
            {'product_tmpl_id': template.id, 'attribute_id': self.attr_profile.id,
             'value_ids': [(6, 0, [])]},
            {'product_tmpl_id': template.id, 'attribute_id': self.attr_color.id,
             'value_ids': [(6, 0, (self.color_red + self.color_blue).ids)]},
            {'product_tmpl_id': template.id, 'attribute_id': self.attr_length.id,
             'value_ids': [(6, 0, [])]},
        ])
        return template

    def _configure_cut_piece(self, template, profile, colour, length):
        """Materialise the open values of a cut piece and build the variant."""
        lines = {line.attribute_id: line for line in template.attribute_line_ids}
        ptavs = (
            lines[self.attr_profile]._get_or_create_ptav({'reference': profile})
            + lines[self.attr_color].product_template_value_ids.filtered(
                lambda ptav: ptav.product_attribute_value_id == colour)
            + lines[self.attr_length]._get_or_create_ptav({'number': length})
        )
        return template._create_product_variant(ptavs)

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
