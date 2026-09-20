# -*- coding: utf-8 -*-
"""Forcing the sender: what gets rewritten, and what does not.

The case this module is for is a multi-company installation where the companies do not
share a mail domain, and each company's people must go out through that company's own
mailbox. So the tests are shaped that way: two companies, two alias domains, two servers,
and the question is always whether a message leaves through the right one.

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
        Domain = cls.env['mail.alias.domain']
        Company = cls.env['res.company']

        # Two companies that do not share a domain, which is the setup this module is for.
        cls.domain_alpha = Domain.create({'name': 'alpha.example.com'})
        cls.domain_beta = Domain.create({'name': 'beta.example.com'})
        cls.company_alpha = Company.create({
            'name': 'Alpha Corp', 'alias_domain_id': cls.domain_alpha.id})
        cls.company_beta = Company.create({
            'name': 'Beta Corp', 'alias_domain_id': cls.domain_beta.id})

        cls.server_alpha = Server.create({
            'name': 'Alpha',
            'smtp_host': 'smtp.alpha.example.com',
            'smtp_user': 'ventas@alpha.example.com',
            'from_filter': 'alpha.example.com',
            'force_smtp_sender': True,
        })
        cls.server_beta = Server.create({
            'name': 'Beta',
            'smtp_host': 'smtp.beta.example.com',
            'smtp_user': 'ventas@beta.example.com',
            'from_filter': 'beta.example.com',
            'force_smtp_sender': False,
        })

    # EmailMessage's policy normalises the header when it is set: '"Juan Perez" <a@b>'
    # comes back as 'Juan Perez <a@b>', because the quotes are not needed. The expected
    # values are therefore built with formataddr instead of written by hand.
    NOMBRE = 'Juan Perez'
    AJENO = 'juan@alpha.example.com'
    OTRA_EMPRESA = 'juan@beta.example.com'
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
        message came back untouched.

        The company is the one that owns the mailbox's domain, not `self.env.company`:
        in a multi-company database the sending context is whoever happens to be running
        the cron."""
        msg = self._make_msg('no-name@alpha.example.com')
        result = self.server_alpha._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr(('Alpha Corp', self.ALPHA)))
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

    # ------------------------------------------------------------------
    # Multi-company: the mail of one company must not leave through another's mailbox
    # ------------------------------------------------------------------

    def test_08_the_owning_company_comes_from_the_domain(self):
        self.assertEqual(self.server_alpha._numa_owner_company(), self.company_alpha)
        self.assertEqual(self.server_beta._numa_owner_company(), self.company_beta)

    def test_09_an_address_of_another_company_is_not_claimed(self):
        """`_find_mail_server` returns *some* server when nothing matches the From, and
        says so in the log. If the flag were honoured there, Beta's mail would go out of
        Alpha's mailbox -- silently, and with Alpha's address on it."""
        msg = self._make_msg(formataddr((self.NOMBRE, self.OTRA_EMPRESA)))
        with self.assertLogs('odoo.addons.numa_fixed_output_mail.models.ir_mail_server',
                             level='WARNING') as logs:
            result = self.server_alpha._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr((self.NOMBRE, self.OTRA_EMPRESA)),
                         "the message was rewritten with another company's mailbox")
        self.assertIsNone(result.get("Reply-To"))
        self.assertTrue(any('from_filter' in line for line in logs.output), logs.output)

    def test_10_a_server_without_a_filter_claims_everything(self):
        """The single-company setup: no `from_filter` is no claim, and the switch is
        taken at face value. Nothing to cross there."""
        server = self.env['ir.mail_server'].create({
            'name': 'Sin filtro',
            'smtp_host': 'smtp.example.com',
            'smtp_user': 'ventas@example.com',
            'force_smtp_sender': True,
        })
        msg = self._make_msg(formataddr((self.NOMBRE, self.OTRA_EMPRESA)))
        result = server._force_sender_on_message(msg)
        self.assertEqual(result["From"], formataddr((self.NOMBRE, 'ventas@example.com')))

    def test_11_each_company_goes_out_through_its_own_mailbox(self):
        """End to end for the case this module exists for: with both switches on, a
        message from each domain leaves through that domain's mailbox."""
        self.server_beta.force_smtp_sender = True
        for servidor, origen, casilla in (
            (self.server_alpha, self.AJENO, self.ALPHA),
            (self.server_beta, self.OTRA_EMPRESA, 'ventas@beta.example.com'),
        ):
            msg = self._make_msg(formataddr((self.NOMBRE, origen)))
            result = servidor._force_sender_on_message(msg)
            self.assertEqual(result["From"], formataddr((self.NOMBRE, casilla)))
            self.assertEqual(result["Reply-To"], casilla)

    def test_12_the_right_server_is_the_one_the_from_selects(self):
        """The routing this module depends on is Odoo's: `from_filter` decides."""
        elegido, _from = self.env['ir.mail_server']._find_mail_server(
            formataddr((self.NOMBRE, self.AJENO)))
        self.assertEqual(elegido, self.server_alpha)
        elegido, _from = self.env['ir.mail_server']._find_mail_server(
            formataddr((self.NOMBRE, self.OTRA_EMPRESA)))
        self.assertEqual(elegido, self.server_beta)
