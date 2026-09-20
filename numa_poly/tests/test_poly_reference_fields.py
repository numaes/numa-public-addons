# -*- coding: utf-8 -*-
"""
Reference fields must survive the polymorphic create path.

`fields.Reference` subclasses `fields.Selection`, so the guard that filters out
cross-model Selection pollution used to reject every reference: it compared the stored
``"model,id"`` string against a set of bare model names. The value was dropped and only
a warning in the log said so, which made every Reference field on a polymorphic model
silently useless.

The end-to-end counterpart lives in
``numa_poly_test/tests/test_poly_inherited_relational.py``: it needs a model with
a Reference field, and a model can only be registered by a module. It used to sit
here guarded by a ``skipTest`` on a fixture nothing declared, so it never ran.
"""
from odoo import fields
from odoo.tests import tagged, TransactionCase

from ..models.poly import poly_selection_value_is_valid


@tagged('post_install', '-at_install')
class TestPolyReferenceValidation(TransactionCase):

    def _reference_field(self, selection):
        field = fields.Reference(selection=selection)
        field.selection = selection
        return field

    def test_01_well_formed_reference_is_accepted(self):
        field = self._reference_field([('res.partner', 'Partner'),
                                       ('res.users', 'User')])
        self.assertTrue(poly_selection_value_is_valid(field, 'res.partner,5'))
        self.assertTrue(poly_selection_value_is_valid(field, 'res.users,1'))

    def test_02_reference_to_an_unlisted_model_is_rejected(self):
        field = self._reference_field([('res.partner', 'Partner')])
        self.assertFalse(poly_selection_value_is_valid(field, 'res.users,1'))

    def test_03_malformed_reference_is_rejected(self):
        field = self._reference_field([('res.partner', 'Partner')])
        self.assertFalse(poly_selection_value_is_valid(field, 'res.partner'))
        self.assertFalse(poly_selection_value_is_valid(field, 42))

    def test_04_plain_selection_still_validated_by_value(self):
        field = fields.Selection(selection=[('draft', 'Draft'), ('done', 'Done')])
        field.selection = [('draft', 'Draft'), ('done', 'Done')]
        self.assertTrue(poly_selection_value_is_valid(field, 'draft'))
        self.assertFalse(poly_selection_value_is_valid(field, 'new'))

    def test_05_dynamic_selection_is_left_alone(self):
        """A callable selection cannot be checked at this point, so nothing is dropped."""
        field = fields.Selection(selection=lambda self: [('a', 'A')])
        field.selection = lambda self: [('a', 'A')]
        self.assertTrue(poly_selection_value_is_valid(field, 'anything'))

    def test_06_empty_selection_is_left_alone(self):
        """A model extends the selection with selection_add; the base may be empty."""
        field = self._reference_field([])
        self.assertTrue(poly_selection_value_is_valid(field, 'res.partner,5'))
