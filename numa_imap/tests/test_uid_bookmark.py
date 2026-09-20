# -*- coding: utf-8 -*-
"""The UID bookmark, without a socket.

What this module replaces in core is the answer to one question: which messages do we ask
the server for? Core answers "the unseen ones"; this module answers "the ones above the
last UID I processed, under the same UIDVALIDITY". That answer is a pure function of the
record, so it is tested directly, and the IMAP conversation is not.

What is deliberately NOT tested here is the connection object itself: exercising it means
an IMAP server, and a fake one would only assert that the fake behaves like the fake.
"""
from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.numa_imap.models.fetchmail import format_imap_date


@tagged('post_install', '-at_install')
class TestUidBookmark(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env['fetchmail.server'].create({
            'name': 'IMAP de prueba',
            'server_type': 'imap',
            'server': 'imap.example.com',
            'user': 'buzon@example.com',
            'password': 'secreto',
        })

    def test_01_a_mailbox_never_read_starts_at_one(self):
        self.assertEqual(self.server._numa_first_uid(12345), 1)

    def test_02_resuming_asks_for_the_next_uid(self):
        self.server.write({'last_uid': 40, 'last_uid_validity': 12345})
        self.assertEqual(self.server._numa_first_uid(12345), 41)

    def test_03_a_changed_uidvalidity_resets_the_bookmark(self):
        """A UID only means something under the UIDVALIDITY it was issued with. If the
        server renumbers the folder, resuming at `last_uid + 1` would skip everything
        below it -- which would be silent, and permanent."""
        self.server.write({'last_uid': 40, 'last_uid_validity': 12345})
        self.assertEqual(self.server._numa_first_uid(99999), 1)

    def test_04_a_bookmark_without_validity_is_not_trusted(self):
        """Rows written before this module started recording the validity."""
        self.server.write({'last_uid': 40, 'last_uid_validity': 0})
        self.assertEqual(self.server._numa_first_uid(12345), 1)

    def test_05_the_initial_window_defaults_to_a_week(self):
        self.assertFalse(self.server.initially_from)
        self.assertEqual(self.server._numa_initial_date(),
                         date.today() - timedelta(days=7))

    def test_06_the_initial_window_can_be_set(self):
        self.server.initially_from = date(2026, 1, 15)
        self.assertEqual(self.server._numa_initial_date(), date(2026, 1, 15))

    def test_07_imap_dates_are_formatted_the_way_imap_wants(self):
        """IMAP wants `5-Sep-2026`: no zero padding, and the month in English whatever
        the user's language is."""
        self.assertEqual(format_imap_date(date(2026, 9, 5)), '5-Sep-2026')
        self.assertEqual(format_imap_date(date(2026, 12, 31)), '31-Dec-2026')
        self.assertEqual(format_imap_date(date(2026, 1, 1)), '1-Jan-2026')

    def test_08_a_pop_server_keeps_the_core_connection(self):
        """Only IMAP is re-classed; POP has no UIDs and must be left alone. Asserted on
        the decision, not on a connection -- opening one needs a server."""
        pop = self.env['fetchmail.server'].create({
            'name': 'POP de prueba',
            'server_type': 'pop',
            'server': 'pop.example.com',
            'user': 'buzon@example.com',
            'password': 'secreto',
        })
        self.assertEqual(pop._get_connection_type(), 'pop')
        self.assertEqual(self.server._get_connection_type(), 'imap')

    def test_09_the_message_records_which_server_brought_it(self):
        """Core sets `default_fetchmail_server_id` in the context while processing
        incoming mail, but only `mail.mail` has the field. This module declares it on
        `mail.message` so the default lands."""
        self.assertIn('fetchmail_server_id', self.env['mail.message']._fields)
        mensaje = self.env['mail.message'].with_context(
            default_fetchmail_server_id=self.server.id).create({
                'body': '<p>hola</p>', 'message_type': 'email'})
        self.assertEqual(mensaje.fetchmail_server_id, self.server)
