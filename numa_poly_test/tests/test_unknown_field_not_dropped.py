# -*- coding: utf-8 -*-
"""A key that is not a field of anything is an error, not something to drop.

The polymorphic create distributes the values between the model, its bases and the
link fields, and each branch is written as ``if k in <some>._fields``. A key matching
none of them used to fall through all of them: the record was created without it and
nothing was logged. Odoo raises ValueError for an unknown field, but that check lives in
``BaseModel.create``, which the polymorphic branch never calls.

These cases need a polymorphic model, hence this fixture module: `test.test2` adopts
`test.test1`, so `a1` belongs to the base and `a3` to the model itself.
"""
from odoo.tests import tagged, TransactionCase

from odoo.addons.numa_poly.models.poly import POLY_PROPAGATED


@tagged('post_install', '-at_install')
class TestUnknownFieldNotDropped(TransactionCase):

    def test_01_an_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.env['test.test2'].create({'a3': 'own', 'no_such_field': 'x'})

    def test_02_fields_of_the_model_and_of_its_base_are_accepted(self):
        record = self.env['test.test2'].create({'a1': 'from the base', 'a3': 'own'})
        self.assertEqual((record.a1, record.a3), ('from the base', 'own'))

    def test_03_what_poly_propagates_is_still_filtered(self):
        """Values poly itself spreads across the hierarchy may not all apply to every model."""
        record = self.env['test.test2'].with_context(**{POLY_PROPAGATED: True}).create({
            'a3': 'own', 'no_such_field': 'x'})
        self.assertEqual(record.a3, 'own')
