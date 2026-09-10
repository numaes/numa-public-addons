# -*- coding: utf-8 -*-
"""
crm.lead como instancia FSM: la búsqueda por ``has_fsm`` y las vistas que usan el estado.

``has_fsm`` era computado sin ``search`` y el filtro "With Active FSM" lo usaba: eso invalidaba la
vista de búsqueda de crm.lead y las estándar que la heredan. El form, por su parte, seguía usando
``state`` después del renombre a ``fsm_state`` en numa_fsm.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCrmLeadFsm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        definicion = cls.env['fsm.definition'].create({'name': 'Bot de leads'})
        Lead = cls.env['crm.lead']
        cls.activo = Lead.create({'name': 'fsm activo', 'definition_id': definicion.id})
        cls.pausado = Lead.create({'name': 'fsm pausado', 'definition_id': definicion.id})
        cls.terminado = Lead.create({'name': 'fsm terminado', 'definition_id': definicion.id})
        cls.sin_fsm = Lead.create({'name': 'sin fsm'})
        cls.activo.fsm_state = 'running'
        cls.pausado.fsm_state = 'paused'
        cls.terminado.fsm_state = 'ended'
        cls.todos = cls.activo | cls.pausado | cls.terminado | cls.sin_fsm

    def _buscar(self, dominio):
        return self.env['crm.lead'].search(dominio + [('id', 'in', self.todos.ids)])

    def test_01_compute(self):
        self.assertTrue(self.activo.has_fsm)
        self.assertTrue(self.pausado.has_fsm)
        self.assertFalse(self.terminado.has_fsm)
        self.assertFalse(self.sin_fsm.has_fsm)

    def test_02_search_agrees_with_compute(self):
        con = self.todos.filtered('has_fsm')
        sin = self.todos - con
        self.assertEqual(self._buscar([('has_fsm', '=', True)]), con)
        self.assertEqual(self._buscar([('has_fsm', '!=', False)]), con)
        self.assertEqual(self._buscar([('has_fsm', '=', False)]), sin)
        self.assertEqual(self._buscar([('has_fsm', '!=', True)]), sin)

    def test_03_lead_views_validate(self):
        for xmlid, tipo in (('crm.crm_lead_view_form', 'form'),
                            ('crm.view_crm_case_leads_filter', 'search')):
            vista = self.env.ref(xmlid)
            vista._check_xml()
            self.assertTrue(self.env['crm.lead'].get_view(vista.id, tipo)['arch'])
