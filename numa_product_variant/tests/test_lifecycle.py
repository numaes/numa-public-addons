import psycopg2

from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestLifecycle(NumaVariantCommon):
    """Lifecycle of materialised values.

    Materialising a master record per free value is something the industrial
    configurators deliberately avoid — SAP and D365 keep free values in the
    instance valuation. Odoo forces materialisation because variant identity
    is the set of template attribute values, so the cleanup policy is a
    first-class requirement rather than an afterthought.
    """

    def test_gc_archives_unused_materialized_values(self):
        value = self.attr_legend._get_or_create_value({'char': 'Orphan'})
        self.env['product.attribute.value']._gc_materialized_values()
        self.assertFalse(value.active)

    def test_gc_never_touches_curated_values(self):
        self.env['product.attribute.value']._gc_materialized_values()
        self.assertTrue(self.color_red.active)

    def test_gc_keeps_values_used_by_a_template(self):
        template = self._make_cut_piece_template()
        line = template.attribute_line_ids.filtered(
            lambda candidate: candidate.attribute_id == self.attr_profile)
        ptav = line._get_or_create_ptav({'reference': self.profile_l4040})
        self.env['product.attribute.value']._gc_materialized_values()
        self.assertTrue(ptav.product_attribute_value_id.active)

    def test_gc_reports_how_many_it_archived(self):
        self.attr_legend._get_or_create_value({'char': 'Orphan one'})
        self.attr_legend._get_or_create_value({'char': 'Orphan two'})
        archived = self.env['product.attribute.value']._gc_materialized_values()
        self.assertGreaterEqual(archived, 2)

    def test_reentering_an_archived_value_revives_it(self):
        value = self.attr_legend._get_or_create_value({'char': 'Orphan'})
        self.env['product.attribute.value']._gc_materialized_values()
        self.assertFalse(value.active)
        again = self.attr_legend._get_or_create_value({'char': 'Orphan'})
        self.assertEqual(again, value)
        self.assertTrue(again.active)

    @mute_logger('odoo.sql_db')
    def test_referenced_template_cannot_be_deleted(self):
        """ondelete='restrict': deleting a profile that cut pieces reference
        fails loudly instead of leaving dangling pointers."""
        self.attr_profile._get_or_create_value({'reference': self.profile_l4040})
        with self.assertRaises(psycopg2.errors.ForeignKeyViolation):
            with self.env.cr.savepoint():
                self.profile_l4040.unlink()
