from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestResolutionApi(NumaVariantCommon):
    """Public API consumed by downstream modules.

    Pure mechanism: it returns the base material and the candidate variants,
    it never chooses one. Which physical strip a cut piece comes from is a
    bill-of-materials decision, the same way a D365 BOM line resolves its
    component while nesting stays a separate concern.
    """

    def setUp(self):
        super().setUp()
        self.cut = self._make_cut_piece_template()

    def test_get_attribute_reference_returns_the_base_template(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertEqual(
            variant.get_attribute_reference(self.attr_profile),
            self.profile_l4040)

    def test_get_attribute_reference_is_empty_for_a_plain_attribute(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertFalse(variant.get_attribute_reference(self.attr_color))

    def test_get_attribute_references_filters_by_model(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        found = variant.get_attribute_references(model='product.template')
        self.assertEqual(list(found.values()), [self.profile_l4040])
        self.assertEqual(list(found.keys()), [self.attr_profile])

    def test_get_attribute_references_excludes_other_models(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertFalse(
            variant.get_attribute_references(model='product.product'))

    def test_find_matching_variants_leaves_free_attributes_unconstrained(self):
        """Strip length exists on the base template but not on the cut piece,
        so both strip lengths must come back as candidates."""
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        candidates = variant.find_matching_variants(self.profile_l4040)
        strip_values = candidates.mapped(
            'product_template_attribute_value_ids.product_attribute_value_id')
        self.assertEqual(len(candidates), 2)
        self.assertIn(self.strip_6m, strip_values)
        self.assertIn(self.strip_45m, strip_values)

    def test_find_matching_variants_respects_shared_values(self):
        """A red cut piece must not match blue strips."""
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        candidates = variant.find_matching_variants(self.profile_l4040)
        colours = candidates.mapped(
            'product_template_attribute_value_ids.product_attribute_value_id')
        self.assertIn(self.color_red, colours)
        self.assertNotIn(self.color_blue, colours)

    def test_full_joinery_resolution(self):
        """The whole point, in two calls and no domain-specific code."""
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_blue, length=1250.0)
        base = variant.get_attribute_reference(self.attr_profile)
        candidates = variant.find_matching_variants(base)
        self.assertEqual(base, self.profile_l4040)
        self.assertEqual(len(candidates), 2)
        for candidate in candidates:
            values = candidate.product_template_attribute_value_ids.mapped(
                'product_attribute_value_id')
            self.assertIn(self.color_blue, values)
            self.assertIn(self.alloy_6063, values)

    # --- reading the values back ------------------------------------------
    #
    # The mirror of ``configure``. A configurator writes a payload into a
    # variant and later has to read it back to recompute what the variant is
    # made of; without this it goes digging by attribute name, which is how it
    # ends up depending on a label.

    def test_a_number_comes_back_as_a_number(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=1250.0)
        self.assertEqual(variant.get_attribute_value(self.attr_length), 1250.0)

    def test_a_reference_comes_back_as_a_record(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertEqual(variant.get_attribute_value(self.attr_profile),
                         self.profile_l4040)

    def test_a_plain_value_comes_back_as_its_name(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_blue, length=800.0)
        self.assertEqual(variant.get_attribute_value(self.attr_color), 'Blue')

    def test_an_absent_attribute_gives_the_default_and_not_zero(self):
        """Una dimension omitida y una dimension en cero no son lo mismo."""
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        self.assertIsNone(variant.get_attribute_value(self.attr_size))
        self.assertEqual(
            variant.get_attribute_value(self.attr_size, default=0.0), 0.0)

    def test_every_value_at_once_is_keyed_by_attribute(self):
        variant = self._configure_cut_piece(
            self.cut, profile=self.profile_l4040,
            colour=self.color_red, length=800.0)
        values = variant.get_attribute_values()
        self.assertEqual(values[self.attr_length], 800.0)
        self.assertEqual(values[self.attr_profile], self.profile_l4040)
        self.assertEqual(values[self.attr_color], 'Red')


    def test_configure_reaches_a_curated_value(self):
        """Un valor de lista cerrada no lleva clave canonica, y aun asi se pide.

        Todo valor de un atributo cerrado nace de un archivo de datos o del
        formulario del atributo, o sea sin materializar. Si `configure` no
        pudiera nombrarlos, el unico mensaje posible seria el que seguro es
        falso: "Red no es un valor permitido de Color", sobre el Red que el
        atributo lista.
        """
        variant = self.cut.configure({
            self.attr_profile: {'reference': self.profile_l4040},
            self.attr_color: {'char': 'Red'},
            self.attr_length: {'number': 1750.0},
        })
        self.assertEqual(variant.get_attribute_value(self.attr_color), 'Red')
        self.assertEqual(variant.get_attribute_value(self.attr_length), 1750.0)
        self.assertEqual(variant.get_attribute_value(self.attr_profile),
                         self.profile_l4040)

    def test_a_curated_value_is_found_and_not_duplicated(self):
        before = self.env['product.attribute.value'].search_count(
            [('attribute_id', '=', self.attr_color.id)])
        self.cut.configure({
            self.attr_profile: {'reference': self.profile_l4040},
            self.attr_color: {'char': 'Red'},
            self.attr_length: {'number': 1751.0},
        })
        self.assertEqual(
            self.env['product.attribute.value'].search_count(
                [('attribute_id', '=', self.attr_color.id)]),
            before, 'volvio a crear un valor que ya estaba')

    def test_a_value_the_attribute_does_not_list_is_still_refused(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.cut.configure({
                self.attr_profile: {'reference': self.profile_l4040},
                self.attr_color: {'char': 'Verde fosforescente'},
                self.attr_length: {'number': 1752.0},
            })
