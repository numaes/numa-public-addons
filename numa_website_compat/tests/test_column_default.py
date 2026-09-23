# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestColumnDefault(TransactionCase):

    def test_01_the_column_has_the_field_default(self):
        self.env.cr.execute("""
            SELECT column_default FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'ir_ui_view' AND column_name = 'visibility'""")
        default = self.env.cr.fetchone()[0] or ''
        self.assertIn("'%s'" % self.env['ir.ui.view']._fields['visibility'].default(self.env['ir.ui.view']),
                      default)

    def test_02_an_insert_that_does_not_know_the_field_succeeds(self):
        """What a module loaded before website does during an upgrade."""
        self.env.cr.execute("""
            INSERT INTO ir_ui_view (name, model, type, arch_db, mode, priority, active)
            VALUES ('numa probe', 'res.partner', 'list', '{"en_US": "<list/>"}', 'primary', 16, true)
            RETURNING visibility""")
        self.assertEqual(self.env.cr.fetchone()[0], 'public')
