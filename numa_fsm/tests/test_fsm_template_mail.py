# -*- coding: utf-8 -*-
"""
Mails de plantilla de una instancia FSM (``action_send_template_mail``).

El asunto se renderizaba con miniqweb, que parsea XML: con texto plano —el caso normal de un
asunto— fallaba con AttributeError, y quien lo llamaba dentro de un try (el pedido de
documentación de alfy_synch) nunca mandaba el mail. El cuerpo con varios elementos en la raíz se
truncaba en silencio al primero.
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
