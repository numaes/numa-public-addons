# -*- coding: utf-8 -*-
"""Un valor inválido de Selection no se descarta en silencio.

Poly filtra valores de Selection que no valen en el modelo destino. Existe por una razón real: al
crear un registro polimórfico, los vals del modelo de origen se propagan a los otros modelos de la
jerarquía, y un `state='new'` válido en `conversation.message` no lo es en `fsm.instance`.

Pero el filtrado se aplicaba a CUALQUIER create, incluido el que un llamador pide derecho sobre un
modelo común. Ahí un valor inválido es un error y le toca a Odoo rechazarlo: descartarlo deja el
registro creado sin ese dato, con el llamador convencido de que se guardó. Pasó de verdad — una
importación creó 73 documentos perdiendo su tipo, y el único rastro fue un WARNING en el log.
"""
from odoo.tests import tagged, TransactionCase

from ..models.poly import POLY_PROPAGATED


@tagged('post_install', '-at_install')
class TestSelectionInvalidaNoSeDescarta(TransactionCase):

    def test_01_un_create_directo_con_valor_invalido_falla(self):
        """El llamador pidió ese valor: si no vale, tiene que enterarse."""
        with self.assertRaises(ValueError):
            self.env['ir.attachment'].create({
                'name': 'prueba.txt',
                'type': 'no-existe',        # type es Selection: url / binary
            })

    def test_02_un_create_directo_con_valor_valido_guarda(self):
        att = self.env['ir.attachment'].create({'name': 'prueba.txt', 'type': 'url',
                                                'url': 'https://example.test/x'})
        self.assertEqual(att.type, 'url')

    def test_03_lo_propagado_por_poly_se_sigue_filtrando(self):
        """La razón por la que el filtro existe: el valor vino de OTRO modelo, no del llamador.

        Se crea igual, sin el campo ajeno, en vez de romper la creación del registro polimórfico.
        """
        att = self.env['ir.attachment'].with_context(**{POLY_PROPAGATED: True}).create({
            'name': 'propagado.txt',
            'type': 'no-existe',
        })
        self.assertTrue(att.exists())
        self.assertNotEqual(att.type, 'no-existe')
