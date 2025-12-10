from email.message import EmailMessage

from odoo.tests.common import TransactionCase


class TestForceSmtpSender(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server_alpha = cls.env.ref("numa_fixed_output_mail.demo_mail_server_alpha")
        cls.server_beta = cls.env.ref("numa_fixed_output_mail.demo_mail_server_beta")

    def _make_msg(self, from_header):
        msg = EmailMessage()
        msg["From"] = from_header
        msg["To"] = "customer@example.com"
        msg["Subject"] = "Test"
        msg.set_content("Body")
        return msg

    def test_no_change_when_flag_disabled(self):
        # server_beta has force_smtp_sender = False
        msg = self._make_msg('"Juan Perez" <juan@usuario.com>')
        result = self.server_beta._force_sender_on_message(msg)
        self.assertEqual(result["From"], '"Juan Perez" <juan@usuario.com>')
        self.assertIsNone(result.get("Reply-To"))
        self.assertIsNone(result.get("Return-Path"))

    def test_force_when_flag_enabled_preserve_display_name(self):
        # server_alpha has force_smtp_sender = True and smtp_user set
        msg = self._make_msg('"Juan Perez" <juan@usuario.com>')
        result = self.server_alpha._force_sender_on_message(msg)
        self.assertEqual(result["From"], '"Juan Perez" <ventas@alpha.example.com>')
        self.assertEqual(result["Reply-To"], 'ventas@alpha.example.com')
        self.assertEqual(result["Return-Path"], 'ventas@alpha.example.com')

    def test_force_when_no_display_name_uses_company_or_server(self):
        msg = self._make_msg('no-name@usuario.com')
        result = self.server_alpha._force_sender_on_message(msg)
        # Display name should be company name (Alpha Corp) per demo data
        self.assertEqual(result["From"], 'Alpha Corp <ventas@alpha.example.com>')
        self.assertEqual(result["Reply-To"], 'ventas@alpha.example.com')
        self.assertEqual(result["Return-Path"], 'ventas@alpha.example.com')

    def test_force_when_already_same_address(self):
        # If from address already equals smtp_user, only ensure headers are set accordingly
        msg = self._make_msg('"Juan Perez" <ventas@alpha.example.com>')
        result = self.server_alpha._force_sender_on_message(msg)
        self.assertEqual(result["From"], '"Juan Perez" <ventas@alpha.example.com>')
        self.assertEqual(result["Reply-To"], 'ventas@alpha.example.com')
        self.assertEqual(result["Return-Path"], 'ventas@alpha.example.com')
