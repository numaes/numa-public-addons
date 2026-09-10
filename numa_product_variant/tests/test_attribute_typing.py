from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestAttributeTyping(NumaVariantCommon):
    """Type declaration on product.attribute.

    `value_type` is orthogonal to `create_variant` and to `display_type`: it
    says what kind of data a value carries, not how it is rendered nor whether
    it produces a variant.
    """

    def test_default_value_type_is_char(self):
        """Existing attributes keep behaving as plain text attributes."""
        self.assertEqual(self.attr_color.value_type, 'char')
        self.assertFalse(self.attr_color.allow_additional_values)

    def test_reference_attribute_declares_a_model(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type',
            'create_variant': 'dynamic',
            'code_identifier': 'P',
            'value_type': 'reference',
            'reference_model': 'product.template',
        })
        self.assertEqual(attr.reference_model, 'product.template')

    def test_reference_attribute_requires_a_model(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken reference',
                'value_type': 'reference',
            })

    def test_number_bounds_must_be_ordered(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken bounds',
                'value_type': 'number',
                'number_min': 100.0,
                'number_max': 10.0,
            })

    def test_number_rounding_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken rounding',
                'value_type': 'number',
                'number_rounding': 0.0,
            })


@tagged('post_install', '-at_install')
class TestReferencePayload(NumaVariantCommon):
    """Record references carried by attribute values.

    The reference lives on product.attribute.value and is overridable on
    product.template.attribute.value for a single template.
    """

    def test_value_reference_round_trip(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type', 'create_variant': 'dynamic',
            'value_type': 'reference', 'reference_model': 'product.template',
        })
        base = self._make_template(name='Profile L 40x40', base_code='L4040')
        value = self.env['product.attribute.value'].create({
            'name': 'L 40x40', 'attribute_id': attr.id, 'code_value': 'L4040',
            'reference_model': 'product.template',
            'reference_template_id': base.id,
        })
        self.assertEqual(value._get_reference_record(), base)
        self.assertEqual(value.reference_record, base)

    def test_ptav_overrides_the_value_reference(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type', 'create_variant': 'always',
            'value_type': 'reference', 'reference_model': 'product.template',
        })
        base = self._make_template(name='Profile A', base_code='A')
        override = self._make_template(name='Profile B', base_code='B')
        value = self.env['product.attribute.value'].create({
            'name': 'A', 'attribute_id': attr.id, 'code_value': 'A',
            'reference_model': 'product.template',
            'reference_template_id': base.id,
        })
        tmpl = self._make_template(name='Cut piece', base_code='CUT')
        self.env['product.template.attribute.line'].create({
            'product_tmpl_id': tmpl.id, 'attribute_id': attr.id,
            'value_ids': [(6, 0, value.ids)],
        })
        ptav = tmpl.attribute_line_ids.filtered(
            lambda line: line.attribute_id == attr).product_template_value_ids
        self.assertEqual(ptav._get_effective_reference(), base)

        ptav.write({
            'reference_model': 'product.template',
            'reference_template_id': override.id,
        })
        self.assertEqual(ptav._get_effective_reference(), override)

    def test_reference_cycle_is_rejected(self):
        attr = self.env['product.attribute'].create({
            'name': 'Alias', 'value_type': 'reference',
            'reference_model': 'product.attribute.value',
        })
        first = self.env['product.attribute.value'].create({
            'name': 'first', 'attribute_id': attr.id, 'code_value': 'F',
        })
        second = self.env['product.attribute.value'].create({
            'name': 'second', 'attribute_id': attr.id, 'code_value': 'S',
            'reference_model': 'product.attribute.value',
            'reference_value_id': first.id,
        })
        with self.assertRaises(ValidationError):
            first.write({
                'reference_model': 'product.attribute.value',
                'reference_value_id': second.id,
            })

    def test_reference_domain_is_enforced(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type', 'value_type': 'reference',
            'reference_model': 'product.template',
            'reference_domain': "[('base_code', '=like', 'L%')]",
        })
        outside = self._make_template(name='Not a profile', base_code='X1')
        with self.assertRaises(ValidationError):
            self.env['product.attribute.value'].create({
                'name': 'X1', 'attribute_id': attr.id, 'code_value': 'X1',
                'reference_model': 'product.template',
                'reference_template_id': outside.id,
            })

    def test_reference_domain_accepts_matching_records(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type', 'value_type': 'reference',
            'reference_model': 'product.template',
            'reference_domain': "[('base_code', '=like', 'L%')]",
        })
        inside = self._make_template(name='Profile L', base_code='L1')
        value = self.env['product.attribute.value'].create({
            'name': 'L1', 'attribute_id': attr.id, 'code_value': 'L1',
            'reference_model': 'product.template',
            'reference_template_id': inside.id,
        })
        self.assertEqual(value._get_reference_record(), inside)


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestNumericUnit(NumaVariantCommon):
    """A numeric attribute declares the unit its values are typed in.

    Dimensions are stored in metres. Anybody configuring a roof or a window
    thinks in millimetres, and without a declared unit 1200 mm reached
    ``variant_length`` as 1200 metres.
    """

    def _length_attribute(self, uom, rounding=1.0):
        return self.env['product.attribute'].create({
            'name': 'Opening width (%s)' % uom,
            'create_variant': 'always',
            'code_identifier': 'OW',
            'value_type': 'number',
            'number_uom': uom,
            # Rounding is expressed in the attribute's own unit: whole
            # millimetres, or a millimetre expressed in metres.
            'number_rounding': rounding,
            'change_on_create': 'length',
            'allow_additional_values': True,
        })

    def _variant_for(self, attribute, value):
        template = self.env['product.template'].create({
            'name': 'Leaf', 'type': 'consu', 'base_code': 'LF',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, value.ids)],
            })],
        })
        return template.product_variant_ids

    def test_millimetres_reach_the_dimension_as_metres(self):
        attribute = self._length_attribute('mm')
        value = attribute._get_or_create_value({'number': 1200})
        self.assertEqual(value.free_number, 1200.0)
        self.assertEqual(value.value_on_create, 1.2)
        self.assertEqual(self._variant_for(attribute, value).product_length, 1.2)

    def test_centimetres(self):
        attribute = self._length_attribute('cm')
        value = attribute._get_or_create_value({'number': 120})
        self.assertEqual(value.value_on_create, 1.2)

    def test_metres_are_the_default_and_unchanged(self):
        attribute = self._length_attribute('m', rounding=0.001)
        value = attribute._get_or_create_value({'number': 1.2})
        self.assertEqual(value.value_on_create, 1.2)

    def test_the_label_and_the_code_keep_the_entered_unit(self):
        """The user typed 1200; nothing downstream should relabel it 1.2."""
        attribute = self._length_attribute('mm')
        value = attribute._get_or_create_value({'number': 1200})
        self.assertEqual(value.name, '1200')
        self.assertEqual(value.canonical_key, '1200')

    def test_an_attribute_without_a_unit_behaves_as_metres(self):
        attribute = self._length_attribute('mm', rounding=0.001)
        attribute.number_uom = False
        value = attribute._get_or_create_value({'number': 3})
        self.assertEqual(value.value_on_create, 3.0)
