from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install', 'numa_product_variant')
class TestApiContracts(NumaVariantCommon):
    """Small contracts this module used to break quietly."""

    def test_template_write_returns_true(self):
        """A write returning None makes `record.write(...) and ...` false."""
        template = self.env['product.template'].create({
            'name': 'Contract', 'type': 'consu',
        })
        self.assertIs(template.write({'name': 'Renamed'}), True)

    def test_template_write_returns_true_on_the_category_branch(self):
        template = self.env['product.template'].create({
            'name': 'Contract', 'type': 'consu',
        })
        self.assertIs(template.write({'categ_id': self.category.id}), True)

    def test_missing_reference_answers_with_the_declared_model(self):
        attribute = self.env['product.attribute'].create({
            'name': 'Supplier', 'create_variant': 'always',
            'code_identifier': 'SP', 'value_type': 'reference',
            'reference_model': 'product.product',
        })
        template = self.env['product.template'].create({
            'name': 'No reference', 'type': 'consu',
        })
        missing = template.product_variant_id.get_attribute_reference(attribute)
        self.assertFalse(missing)
        self.assertEqual(missing._name, 'product.product')

    def test_a_non_reference_attribute_still_answers_a_recordset(self):
        missing = self.env['product.template'].create({
            'name': 'Plain', 'type': 'consu',
        }).product_variant_id.get_attribute_reference(self.attr_color)
        self.assertFalse(missing)
