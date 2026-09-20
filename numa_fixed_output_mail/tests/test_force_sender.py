# -*- coding: utf-8 -*-
"""Forcing the sender: what gets rewritten, and what does not.

The suite used to reference two demo servers, `numa_fixed_output_mail.demo_mail_server_alpha`
and `..._beta`, that no data file declares -- and `tests/__init__.py` did not import this
module, so nothing ever ran. Both are fixed here: the servers are built by the test, and
the package imports the file.
"""
from email.message import EmailMessage
from email.utils import formataddr

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestForceSmtpSender(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Server = cls.env['ir.mail_server']
        cls.server_alpha = Server.create({
            'name': 'Alpha',
            'smtp_host': 'smtp.alpha.example.com',
            'smtp_user': 'ventas@alpha.example.com',
            'force_smtp_sender': True,
        })
        cls.server_beta = Server.create({
            'name': 'Beta',
            'smtp_host': 'smtp.beta.example.com',
            'smtp_user': 'ventas@beta.example.com',
            'force_smtp_sender': False,
        })

    # EmailMessage's policy normalises the header when it is set: '"Juan Perez" <a@b>'
    # comes back as 'Juan Perez <a@b>', because the quotes are not needed. The expected
    # values are therefore built with formataddr instead of written by hand.
    NOMBRE = 'Juan Perez'
    AJENO = 'juan@usuario.com'
    ALPHA = 'ventas@alpha.example.com'

    def _make_msg(self, from_header):
        msg = EmailMessage()
        msg["From"] = from_header
        msg["To"] = "customer@example.com"
        msg["Subject"] = "Test"
        msg.set_content("Body")
        return msg

    def test_01_no_change_when_flag_disabled(self):
        msg = self._make_msg(formataddr((self.NOMBRE, self.AJENO)))
        result = self.server_beta._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr((self.NOMBRE, self.AJENO)))
        self.assertIsNone(result.get("Reply-To"))
        self.assertIsNone(result.get("Return-Path"))

    def test_02_no_change_without_an_smtp_user(self):
        """The flag alone is not enough: with no user there is no address to force."""
        server = self.env['ir.mail_server'].create({
            'name': 'Sin usuario',
            'smtp_host': 'smtp.example.com',
            'force_smtp_sender': True,
        })
        msg = self._make_msg(formataddr((self.NOMBRE, self.AJENO)))
        result = server._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr((self.NOMBRE, self.AJENO)))

    def test_03_the_display_name_is_preserved(self):
        msg = self._make_msg(formataddr((self.NOMBRE, self.AJENO)))
        result = self.server_alpha._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr((self.NOMBRE, self.ALPHA)))
        self.assertEqual(result["Reply-To"], self.ALPHA)
        self.assertEqual(result["Return-Path"], self.ALPHA)

    def test_04_without_a_display_name_the_company_answers(self):
        """The branch that never ran: it read `self.company_id`, a field
        `ir.mail_server` does not have, so the AttributeError was swallowed and the
        message came back untouched."""
        msg = self._make_msg('no-name@usuario.com')
        result = self.server_alpha._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr((self.env.company.name, self.ALPHA)))
        self.assertEqual(result["Reply-To"], self.ALPHA)
        self.assertEqual(result["Return-Path"], self.ALPHA)

    def test_05_an_address_that_already_matches_is_left_alone(self):
        msg = self._make_msg(formataddr((self.NOMBRE, self.ALPHA)))
        result = self.server_alpha._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr((self.NOMBRE, self.ALPHA)))
        self.assertEqual(result["Reply-To"], self.ALPHA)
        self.assertEqual(result["Return-Path"], self.ALPHA)

    def test_06_the_headers_are_not_duplicated(self):
        """``del`` before setting: an email.message allows repeated headers, and two
        ``From`` lines is a message most providers reject."""
        msg = self._make_msg(formataddr((self.NOMBRE, self.AJENO)))
        result = self.server_alpha._force_sender_on_message(msg)
        for header in ('From', 'Reply-To', 'Return-Path'):
            self.assertEqual(len(result.get_all(header) or []), 1, header)

    def test_07_send_email_goes_through_the_rewrite(self):
        """The seam that matters: the rewrite has to happen on the way out, not only when
        the helper is called by hand. Odoo does not send in test mode, so what is asserted
        is the message the send left behind."""
        msg = self._make_msg(formataddr((self.NOMBRE, self.AJENO)))
        self.env['ir.mail_server'].send_email(msg, mail_server_id=self.server_alpha.id)
        self.assertEqual(msg["From"], formataddr((self.NOMBRE, self.ALPHA)))
        self.assertEqual(msg["Reply-To"], self.ALPHA)
