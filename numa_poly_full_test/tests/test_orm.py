# -*- coding: utf-8 -*-
"""
ORM integration tests for numa_poly using the poly.ft.* diamond hierarchy.

Covers: create, write, unlink, search, method dispatch, and fields_get.
These tests exercise the full stack — from the poly engine through the ORM
to the database — ensuring that field injection and record linking work
correctly end-to-end.
"""
import logging
from odoo.tests import tagged, TransactionCase

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'poly_orm')
class TestPolyORM(TransactionCase):
    """Full ORM tests for the poly.ft.* diamond hierarchy."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def test_create_base_record(self):
        """Create a poly.ft.base record and verify native fields are stored."""
        rec = self.env['poly.ft.base'].create({'name': 'Base One', 'value': 10})
        self.assertEqual(rec.name, 'Base One')
        self.assertEqual(rec.value, 10)

    def test_create_alpha_sets_injected_fields(self):
        """Creating poly.ft.alpha with name/value stores them on the base record."""
        rec = self.env['poly.ft.alpha'].create({
            'name': 'Alpha One',
            'value': 20,
            'alpha_note': 'note-a',
        })
        self.assertEqual(rec.name, 'Alpha One')
        self.assertEqual(rec.value, 20)
        self.assertEqual(rec.alpha_note, 'note-a')

    def test_create_alpha_auto_creates_base_link(self):
        """alpha_base_id must be set automatically after creating an alpha record."""
        rec = self.env['poly.ft.alpha'].create({'name': 'Alpha Link'})
        self.assertTrue(rec.alpha_base_id, "alpha_base_id must be populated after create")

    def test_create_beta_sets_injected_fields(self):
        """Creating poly.ft.beta with name/beta_count stores them correctly."""
        rec = self.env['poly.ft.beta'].create({
            'name': 'Beta One',
            'value': 30,
            'beta_count': 5,
        })
        self.assertEqual(rec.name, 'Beta One')
        self.assertEqual(rec.value, 30)
        self.assertEqual(rec.beta_count, 5)

    def test_create_top_diamond_sets_all_fields(self):
        """poly.ft.top create with name, value, alpha_note, beta_count, top_flag."""
        rec = self.env['poly.ft.top'].create({
            'name': 'Top One',
            'value': 42,
            'alpha_note': 'top-alpha-note',
            'beta_count': 7,
            'top_flag': True,
        })
        self.assertEqual(rec.name, 'Top One')
        self.assertEqual(rec.value, 42)
        self.assertEqual(rec.alpha_note, 'top-alpha-note')
        self.assertEqual(rec.beta_count, 7)
        self.assertTrue(rec.top_flag)

    def test_create_top_auto_creates_alpha_and_beta_links(self):
        """poly.ft.top must auto-populate both top_alpha_id and top_beta_id."""
        rec = self.env['poly.ft.top'].create({'name': 'Top Links'})
        self.assertTrue(rec.top_alpha_id, "top_alpha_id must be populated")
        self.assertTrue(rec.top_beta_id, "top_beta_id must be populated")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def test_write_alpha_injected_field_persists(self):
        """Writing an injected field on poly.ft.alpha persists through the related path."""
        rec = self.env['poly.ft.alpha'].create({'name': 'Before'})
        rec.write({'name': 'After'})
        self.assertEqual(rec.name, 'After')
        # Re-read from database to verify persistence.
        rec.invalidate_recordset()
        self.assertEqual(rec.name, 'After')

    def test_write_top_diamond_injected_field_persists(self):
        """Writing name on poly.ft.top (diamond) persists correctly."""
        rec = self.env['poly.ft.top'].create({'name': 'Before', 'value': 1})
        rec.write({'name': 'After Diamond', 'value': 99})
        rec.invalidate_recordset()
        self.assertEqual(rec.name, 'After Diamond')
        self.assertEqual(rec.value, 99)

    def test_write_alpha_note_on_top(self):
        """Writing alpha_note on poly.ft.top (via alpha → base chain) persists."""
        rec = self.env['poly.ft.top'].create({'name': 'Top Note', 'alpha_note': 'old'})
        rec.write({'alpha_note': 'new-note'})
        rec.invalidate_recordset()
        self.assertEqual(rec.alpha_note, 'new-note')

    def test_write_top_flag_native_field(self):
        """top_flag is a native field on poly.ft.top — write must persist directly."""
        rec = self.env['poly.ft.top'].create({'name': 'Flagged', 'top_flag': False})
        rec.write({'top_flag': True})
        rec.invalidate_recordset()
        self.assertTrue(rec.top_flag)

    # ------------------------------------------------------------------
    # Unlink
    # ------------------------------------------------------------------

    def test_unlink_alpha_removes_record(self):
        """Unlinking an alpha record must remove it from the model."""
        rec = self.env['poly.ft.alpha'].create({'name': 'To Delete'})
        rec_id = rec.id
        rec.unlink()
        remaining = self.env['poly.ft.alpha'].search([('id', '=', rec_id)])
        self.assertFalse(remaining, "Record must be gone after unlink")

    def test_unlink_top_removes_record(self):
        """Unlinking a poly.ft.top record must remove it."""
        rec = self.env['poly.ft.top'].create({'name': 'Top Delete'})
        rec_id = rec.id
        rec.unlink()
        remaining = self.env['poly.ft.top'].search([('id', '=', rec_id)])
        self.assertFalse(remaining)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def test_search_by_injected_name_on_alpha(self):
        """Searching poly.ft.alpha by the injected 'name' field must find the record."""
        rec = self.env['poly.ft.alpha'].create({'name': 'SearchTarget'})
        results = self.env['poly.ft.alpha'].search([('name', '=', 'SearchTarget')])
        self.assertIn(rec, results)

    def test_search_by_injected_name_on_top(self):
        """Searching poly.ft.top by 'name' must find the diamond record."""
        rec = self.env['poly.ft.top'].create({'name': 'TopSearch'})
        results = self.env['poly.ft.top'].search([('name', '=', 'TopSearch')])
        self.assertIn(rec, results)

    def test_search_by_alpha_note_on_top(self):
        """Searching poly.ft.top by alpha_note (injected via alpha chain) must work."""
        rec = self.env['poly.ft.top'].create({
            'name': 'NotedTop',
            'alpha_note': 'unique-note-xyz',
        })
        results = self.env['poly.ft.top'].search([('alpha_note', '=', 'unique-note-xyz')])
        self.assertIn(rec, results)

    def test_search_returns_empty_for_no_match(self):
        """Search on non-existent value must return empty recordset."""
        results = self.env['poly.ft.alpha'].search([('name', '=', '__nonexistent__')])
        self.assertFalse(results)

    # ------------------------------------------------------------------
    # Method dispatch
    # ------------------------------------------------------------------

    def test_method_dispatch_base(self):
        """make_uppercase on poly.ft.base uppercases the name."""
        rec = self.env['poly.ft.base'].create({'name': 'hello'})
        rec.make_uppercase()
        self.assertEqual(rec.name, 'HELLO')

    def test_method_dispatch_alpha_inherits_base(self):
        """poly.ft.alpha.make_uppercase is inherited from poly.ft.base."""
        rec = self.env['poly.ft.alpha'].create({'name': 'alpha'})
        rec.make_uppercase()
        self.assertEqual(rec.name, 'ALPHA')

    def test_method_dispatch_beta_inherits_base(self):
        """poly.ft.beta.make_uppercase is inherited from poly.ft.base."""
        rec = self.env['poly.ft.beta'].create({'name': 'beta'})
        rec.make_uppercase()
        self.assertEqual(rec.name, 'BETA')

    def test_method_dispatch_top_override(self):
        """poly.ft.top.make_uppercase overrides base: uppercases then appends '_TOP'
        and sets top_flag=True."""
        rec = self.env['poly.ft.top'].create({'name': 'top', 'top_flag': False})
        rec.make_uppercase()
        self.assertEqual(rec.name, 'TOP_TOP')
        self.assertTrue(rec.top_flag)

    # ------------------------------------------------------------------
    # fields_get
    # ------------------------------------------------------------------

    def test_fields_get_alpha_includes_injected_fields(self):
        """fields_get on poly.ft.alpha must include 'name' and 'value'."""
        fget = self.env['poly.ft.alpha'].fields_get(['name', 'value'])
        self.assertIn('name', fget)
        self.assertIn('value', fget)

    def test_fields_get_top_includes_all_chain_fields(self):
        """fields_get on poly.ft.top must include name, value, alpha_note, beta_count."""
        fget = self.env['poly.ft.top'].fields_get(
            ['name', 'value', 'alpha_note', 'beta_count', 'top_flag']
        )
        for fname in ('name', 'value', 'alpha_note', 'beta_count', 'top_flag'):
            with self.subTest(field=fname):
                self.assertIn(fname, fget, f"'{fname}' must appear in poly.ft.top.fields_get()")

    def test_fields_get_top_name_is_char(self):
        """The injected 'name' field on poly.ft.top must be reported as char."""
        fget = self.env['poly.ft.top'].fields_get(['name'])
        self.assertEqual(fget['name']['type'], 'char')

    def test_fields_get_top_value_is_integer(self):
        """The injected 'value' field on poly.ft.top must be reported as integer."""
        fget = self.env['poly.ft.top'].fields_get(['value'])
        self.assertEqual(fget['value']['type'], 'integer')
