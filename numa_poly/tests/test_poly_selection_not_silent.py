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
