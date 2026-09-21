"""The rules: what gets synchronised, and which slice of it."""

from datetime import datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestSynchRule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env['numa.synch.rule']
        cls.partner_model_id = cls.env['ir.model']._get_id('res.partner')

    def _rule(self, **overrides):
        vals = {
            'name': 'Partners',
            'model_id': self.partner_model_id,
        }
        vals.update(overrides)
        return self.Rule.create(vals)

    def test_01_the_model_name_follows_the_model(self):
        rule = self._rule()

        self.assertEqual(rule.model_name, 'res.partner')

    def test_02_a_first_sync_sends_everything_the_filter_allows(self):
        """With no last sync there is no delta: the filter alone decides."""
        rule = self._rule(domain_filter="[('is_company', '=', True)]")

        self.assertEqual(rule.get_delta_domain(False),
                         [('is_company', '=', True)])

    def test_03_a_later_sync_only_sends_what_changed(self):
        rule = self._rule(domain_filter="[('is_company', '=', True)]")
        since = datetime(2026, 1, 1, 12, 0, 0)

        domain = rule.get_delta_domain(since)

        self.assertTrue(self.env['res.partner'].search(domain) is not None)
        self.assertIn(('write_date', '>', since), list(domain))
        self.assertIn(('is_company', '=', True), list(domain))

    def test_04_the_delta_window_actually_selects(self):
        """The two halves are ANDed, not ORed -- an OR would send the whole table."""
        rule = self._rule()
        old = self.env['res.partner'].create({'name': 'Settled Long Ago'})
        # The row has to be in the table before SQL can age it.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET write_date = %s WHERE id = %s",
            (datetime.now() - timedelta(days=30), old.id))
        old.invalidate_recordset()
        fresh = self.env['res.partner'].create({'name': 'Just Now'})
        self.env.flush_all()

        selected = self.env['res.partner'].search(
            rule.get_delta_domain(datetime.now() - timedelta(hours=1)))

        self.assertIn(fresh, selected)
        self.assertNotIn(old, selected)

    @mute_logger('odoo.addons.numa_synch.models.numa_synch_rule')
    def test_05_a_domain_that_cannot_be_read_falls_back_to_everything(self):
        """A broken filter must not stop the cycle; it is logged and widened.

        The constraint below is what keeps one from being saved in the first place;
        this covers a value that got in some other way, an import or a raw write.
        """
        rule = self._rule()
        self.env.cr.execute(
            "UPDATE numa_synch_rule SET domain_filter = %s WHERE id = %s",
            ('[(not a domain', rule.id))
        rule.invalidate_recordset()

        self.assertEqual(rule.get_delta_domain(False), [])

    def test_06_an_invalid_domain_cannot_be_saved(self):
        with self.assertRaises(ValidationError):
            self._rule(domain_filter='[(not a domain')

    def test_07_a_domain_that_is_not_a_list_cannot_be_saved(self):
        with self.assertRaises(ValidationError):
            self._rule(domain_filter="{'a': 1}")

    def test_08_an_empty_domain_filter_is_allowed(self):
        rule = self._rule(domain_filter='')

        self.assertEqual(rule.get_delta_domain(False), [])
