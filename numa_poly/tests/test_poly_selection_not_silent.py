# -*- coding: utf-8 -*-
"""An invalid Selection value is not discarded silently.

Poly filters out Selection values that are not valid on the target model. It exists for a real
reason: when creating a polymorphic record, the vals of the originating model are propagated to the
other models of the hierarchy, and a `state='new'` that is valid in `conversation.message` is not
valid in `fsm.instance`.

But the filtering was applied to ANY create, including the one a caller asks for directly on a
common model. There an invalid value is an error and it is Odoo's job to reject it: discarding it
leaves the record created without that data, with the caller convinced that it was saved. It really
happened - an import created 73 documents losing their type, and the only trace was a WARNING in the
log.
"""
from odoo.tests import tagged, TransactionCase

from ..models.poly import POLY_PROPAGATED


@tagged('post_install', '-at_install')
class TestSelectionInvalidaNoSeDescarta(TransactionCase):

    def test_01_un_create_directo_con_valor_invalido_falla(self):
        """The caller asked for that value: if it is not valid, they have to find out."""
        with self.assertRaises(ValueError):
            self.env['ir.attachment'].create({
                'name': 'prueba.txt',
                'type': 'no-existe',        # type is a Selection: url / binary
            })

    def test_02_un_create_directo_con_valor_valido_guarda(self):
        att = self.env['ir.attachment'].create({'name': 'prueba.txt', 'type': 'url',
                                                'url': 'https://example.test/x'})
        self.assertEqual(att.type, 'url')

    def test_03_lo_propagado_por_poly_se_sigue_filtrando(self):
        """The reason the filter exists: the value came from ANOTHER model, not from the caller.

        It is created anyway, without the foreign field, instead of breaking the creation of the
        polymorphic record.
        """
        att = self.env['ir.attachment'].with_context(**{POLY_PROPAGATED: True}).create({
            'name': 'propagado.txt',
            'type': 'no-existe',
        })
        self.assertTrue(att.exists())
        self.assertNotEqual(att.type, 'no-existe')

    def test_04_una_seleccion_en_tupla_tambien_se_valida(self):
        """Odoo 20 hands ``field.selection`` over as a tuple, not as a list.

        When the filter demanded a list, it took everything as valid and never filtered.
        """
        from ..models.poly import poly_selection_value_is_valid
        campo = self.env['ir.attachment']._fields['type']
        self.assertNotIsInstance(campo.selection, list, "if this changes, review the filter")
        self.assertTrue(poly_selection_value_is_valid(campo, 'url'))
        self.assertFalse(poly_selection_value_is_valid(campo, 'no-existe'))

    def test_05_una_seleccion_armada_en_ejecucion_se_deja_pasar(self):
        """There is nothing to compare it against, so nothing is discarded."""
        from ..models.poly import poly_selection_value_is_valid

        class CampoFalso:
            selection = staticmethod(lambda model: [('a', 'A')])
        self.assertTrue(poly_selection_value_is_valid(CampoFalso(), 'lo-que-sea'))


@tagged('post_install', '-at_install')
class TestCampoDesconocidoNoSeDescarta(TransactionCase):
    """A key that is not a field of anything is an error, not something to drop.

    The polymorphic create distributes the values between this model, its bases and the
    link fields, and each branch is written as ``if k in <some>._fields``. A key matching
    none of them fell through all of them: the record was created without it and nothing
    was logged. Odoo raises ValueError for an unknown field, but that check lives in
    ``BaseModel.create``, which the polymorphic branch never calls.

    Found on the Odoo 20 migration: ``res.partner.mobile`` was removed, and
    ``create({'mobile': ...})`` returned a partner with the number thrown away, while
    ``search([('mobile', '=', ...)])`` raised as it should.
    """

    # The polymorphic cases (an unknown key rejected, a base field accepted, a propagated
    # key filtered) run in numa_poly_test on a polymorphic fixture model:
    # res.partner is polymorphic only when another module adopts it, and on a plain
    # res.partner those cases exercise Odoo's own create, not poly's.

    def test_02_el_caso_real_de_la_migracion(self):
        """`mobile` was merged into `phone` in Odoo 20."""
        self.assertNotIn('mobile', self.env['res.partner']._fields)
        with self.assertRaises(ValueError):
            self.env['res.partner'].create({
                'name': 'Prueba mobile',
                'mobile': '+54 9 11 6123 4567',
            })


@tagged('post_install', '-at_install')
class TestUnRelatedInyectadoNoLlevaDefault(TransactionCase):
    """A default belongs to the model that STORES the field.

    numa_poly injects the base's fields into the concrete model as non-stored related
    ones. Copied along with them came the base field's `default`, and that turns every
    create of the concrete model into a write on the base: Odoo applies the default to
    the related field, and writing a related field writes THROUGH to its target.

    Found on the Odoo 20 migration, in the Twilio channel. A `conversation.message`
    created with `direction='inbound'` flipped to 'outbound' the moment a
    `conversation.message.twilio` row was attached to it, because that model's injected
    `direction` carried `default='outbound'` from the base. Every inbound message was
    recorded as an outgoing one.
    """

    def setUp(self):
        super().setUp()
        if 'conversation.message.twilio' not in self.env:
            self.skipTest('numa_conversation_engine_twilio is not installed')
        self.driver = self.env['conversation.driver'].search([], limit=1)
        if not self.driver:
            self.skipTest('no conversation.driver to hang a message on')

    def test_01_el_related_inyectado_no_tiene_default(self):
        """The premise, stated directly on the field."""
        campo = self.env['conversation.message.twilio']._fields['direction']
        self.assertTrue(campo.related, "this test is about an injected related field")
        self.assertFalse(campo.store)
        self.assertFalse(
            campo.default,
            "a non-stored related field must not carry the base field's default")

    def test_02_un_valor_de_la_base_sobrevive_al_hijo(self):
        mensaje = self.env['conversation.message'].create({
            'body': '<p>entrante</p>', 'direction': 'inbound', 'driver_id': self.driver.id})
        self.assertEqual(mensaje.direction, 'inbound')

        self.env['conversation.message.twilio'].create({
            'poly_id': mensaje.id, 'twilio_sid': 'SM-prueba'})
        mensaje.invalidate_recordset()
        self.assertEqual(mensaje.direction, 'inbound',
                         "the child's default was written through to the base")

    def test_03_lo_que_el_hijo_pide_explicitamente_si_llega_a_la_base(self):
        """The guard removes the default, not the ability to write."""
        mensaje = self.env['conversation.message'].create({
            'body': '<p>entrante</p>', 'direction': 'inbound', 'driver_id': self.driver.id})
        hijo = self.env['conversation.message.twilio'].create({
            'poly_id': mensaje.id, 'twilio_sid': 'SM-prueba-2'})
        hijo.direction = 'outbound'
        mensaje.invalidate_recordset()
        self.assertEqual(mensaje.direction, 'outbound',
                         "an explicit write through the related field must still land")

    def test_04_el_default_sigue_valiendo_donde_el_valor_vive(self):
        mensaje = self.env['conversation.message'].create({
            'body': '<p>sin direccion</p>', 'driver_id': self.driver.id})
        self.assertEqual(mensaje.direction, 'outbound',
                         "the base model keeps its own default")
