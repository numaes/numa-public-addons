"""The identity table: the one piece of state the whole protocol rests on."""

import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestSynchMap(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Map = cls.env['numa.synch.map']

    def test_01_a_mapping_reads_back_both_ways(self):
        self.Map.set_mapping('res.partner', 10, 500, 'NODE-A')

        self.assertEqual(self.Map.get_remote_id('res.partner', 10, 'NODE-A'), 500)
        self.assertEqual(self.Map.get_local_id('res.partner', 500, 'NODE-A'), 10)

    def test_02_setting_the_same_pair_twice_updates_it(self):
        """Idempotence: a replayed batch must not leave two answers to one question."""
        first = self.Map.set_mapping('res.partner', 11, 501, 'NODE-A')
        second = self.Map.set_mapping('res.partner', 11, 502, 'NODE-A')

        self.assertEqual(first, second)
        self.assertEqual(self.Map.get_remote_id('res.partner', 11, 'NODE-A'), 502)

    def test_03_nodes_do_not_share_an_id_space(self):
        """Two Slaves both have a partner 12, and they are different partners."""
        self.Map.set_mapping('res.partner', 12, 600, 'NODE-A')
        self.Map.set_mapping('res.partner', 13, 600, 'NODE-B')

        self.assertEqual(self.Map.get_local_id('res.partner', 600, 'NODE-A'), 12)
        self.assertEqual(self.Map.get_local_id('res.partner', 600, 'NODE-B'), 13)

    def test_04_models_do_not_share_an_id_space_either(self):
        self.Map.set_mapping('res.partner', 14, 700, 'NODE-A')
        self.Map.set_mapping('res.country', 14, 800, 'NODE-A')

        self.assertEqual(self.Map.get_remote_id('res.partner', 14, 'NODE-A'), 700)
        self.assertEqual(self.Map.get_remote_id('res.country', 14, 'NODE-A'), 800)

    def test_05_an_unknown_pair_is_false_not_an_error(self):
        self.assertFalse(self.Map.get_local_id('res.partner', 999999, 'NODE-A'))
        self.assertFalse(self.Map.get_remote_id('res.partner', 999999, 'NODE-A'))
        self.assertFalse(self.Map.get_remote_id('res.partner', 1, ''))

    def test_06_an_incomplete_mapping_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Map.set_mapping('res.partner', 15, False, 'NODE-A')
        with self.assertRaises(ValidationError):
            self.Map.set_mapping('res.partner', 15, 900, '')

    def test_07_a_model_that_does_not_exist_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Map.set_mapping('no.such.model', 16, 901, 'NODE-A')

    @mute_logger('odoo.sql_db')
    def test_08_the_unique_index_is_real(self):
        """It was declared with `_sql_constraints`, which Odoo 20 ignores.

        Without it the table can hold two answers for one local record, and
        `get_remote_id` returns whichever row comes first -- so a record starts
        arriving at the Master under two different identities.
        """
        self.Map.set_mapping('res.partner', 17, 902, 'NODE-A')

        with self.assertRaises(psycopg2.IntegrityError), self.env.cr.savepoint():
            self.Map.create({
                'model_id': self.env['ir.model']._get_id('res.partner'),
                'local_id': 17,
                'remote_id': 903,
                'node_token': 'NODE-A',
            })

    def test_09_the_display_name_says_which_way_it_points(self):
        mapping = self.Map.set_mapping('res.partner', 18, 904, 'NODE-A')

        self.assertIn('res.partner', mapping.display_name)
        self.assertIn('18', mapping.display_name)
        self.assertIn('904', mapping.display_name)
