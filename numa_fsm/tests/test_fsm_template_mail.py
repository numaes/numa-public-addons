# -*- coding: utf-8 -*-
"""
Template mails of an FSM instance (``action_send_template_mail``).

The subject was rendered with miniqweb, which parses XML: with plain text —the normal case for a
subject— it failed with AttributeError, and whoever called it inside a try (the documentation
request of alfy_synch) never sent the mail. A body with several elements at the root was silently
truncated to the first one.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFsmTemplateMail(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plantilla = cls.env['fsm.wf.mail_template'].create({
            'name': 'aviso',
            'subject': 'Aviso de {{ instance.name }}',
            'body_html': '<p>Primer párrafo</p><p>Segundo de {{ instance.name }}</p>',
        })
        cls.definicion = cls.env['fsm.definition'].create({
            'name': 'Mails de prueba', 'mail_templates': [(6, 0, cls.plantilla.ids)]})
        cls.instancia = cls.env['fsm.instance'].create({
            'name': 'inst-mail', 'definition_id': cls.definicion.id})
        cls.destino = cls.env['res.partner'].create({'name': 'Destino mail FSM'})

    def _enviar(self, subject=None):
        with patch.object(type(self.destino), 'message_notify', autospec=True) as notify:
            self.instancia.action_send_template_mail(self.destino, 'aviso', subject)
        self.assertEqual(notify.call_count, 1)
        return notify.call_args.kwargs

    def test_01_a_plain_text_subject_is_sent_as_is(self):
        self.assertEqual(self._enviar('Pedido de documentación')['subject'], 'Pedido de documentación')

    def test_02_the_template_subject_resolves_its_expressions(self):
        self.assertEqual(self._enviar()['subject'], 'Aviso de inst-mail')

    def test_03_the_body_keeps_every_root_element(self):
        cuerpo = str(self._enviar()['body'])
        self.assertIn('Primer párrafo', cuerpo)
        self.assertIn('Segundo de inst-mail', cuerpo)

    def test_04_rendering_helpers(self):
        self.assertEqual(self.instancia.render_dynamic_text('Hola {{ instance.name }}'), 'Hola inst-mail')
        self.assertEqual(self.instancia.render_dynamic_text(False), '')
        self.assertIn('<div>inst-mail</div>', self.instancia.render_dynamic_html('<div>{{ instance.name }}</div>'))
