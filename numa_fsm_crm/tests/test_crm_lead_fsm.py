# -*- coding: utf-8 -*-
"""
El lead y su instancia FSM: el vínculo explícito, la búsqueda por ``has_fsm`` y las
vistas que muestran el estado.

Hasta 18.0 el lead heredaba ``fsm.instance`` y *era* la instancia. En 20.0 tiene
una: ``fsm_instance_id``. Estos tests fijan lo que el cambio no debía romper —los
mismos nombres de campo en las vistas, el mismo filtro— y lo que ahora sí se puede
afirmar: que el lead existe sin workflow y que la instancia se crea una sola vez.

``has_fsm`` era computado sin ``search`` y el filtro "With Active FSM" lo usaba: eso
invalidaba la vista de búsqueda de crm.lead y las estándar que la heredan.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


def _esquema_minimo():
    """Un diagrama de dos nodos: arranca y se queda esperando en un estado."""
    return {
        'nodes': [
            {'id': 'n_start', 'type': 'start', 'label': 'Start', 'code': ''},
            {'id': 'n_espera', 'type': 'state', 'label': 'Waiting'},
        ],
        'connections': [
            {'fromNodeId': 'n_start', 'fromPortName': '__default__', 'toNodeId': 'n_espera'},
        ],
    }


@tagged('post_install', '-at_install')
class TestCrmLeadFsm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.definicion = cls.env['fsm.definition'].create({'name': 'Bot de leads'})
        Lead = cls.env['crm.lead']
        cls.activo = Lead.create({'name': 'fsm activo', 'definition_id': cls.definicion.id})
        cls.pausado = Lead.create({'name': 'fsm pausado', 'definition_id': cls.definicion.id})
        cls.terminado = Lead.create({'name': 'fsm terminado', 'definition_id': cls.definicion.id})
        cls.sin_fsm = Lead.create({'name': 'sin fsm'})
        for lead, estado in ((cls.activo, 'running'), (cls.pausado, 'paused'),
                             (cls.terminado, 'ended')):
            lead._ensure_fsm_instance().fsm_state = estado
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

    def test_03_search_covers_a_lead_without_instance(self):
        """Con definición pero sin instancia todavía: no tiene FSM activo, y la
        búsqueda negativa tiene que encontrarlo igual."""
        pendiente = self.env['crm.lead'].create(
            {'name': 'con definición, sin instancia', 'definition_id': self.definicion.id})
        self.todos |= pendiente
        self.assertFalse(pendiente.fsm_instance_id)
        self.assertFalse(pendiente.has_fsm)
        self.assertIn(pendiente, self._buscar([('has_fsm', '=', False)]))
        self.assertNotIn(pendiente, self._buscar([('has_fsm', '=', True)]))

    def test_04_lead_views_validate(self):
        for xmlid, tipo in (('crm.crm_lead_view_form', 'form'),
                            ('crm.view_crm_case_leads_filter', 'search')):
            vista = self.env.ref(xmlid)
            vista._check_xml()
            self.assertTrue(self.env['crm.lead'].get_view(vista.id, tipo)['arch'])

    def test_05_lead_and_instance_are_two_records(self):
        """El lead ya no es la instancia. Son dos registros con id propio, y el
        lead sigue existiendo si la instancia se borra."""
        instancia = self.activo.fsm_instance_id
        self.assertTrue(instancia)
        self.assertEqual(instancia._name, 'fsm.instance')
        self.assertEqual(instancia.definition_id, self.definicion)
        instancia.unlink()
        self.assertTrue(self.activo.exists())
        self.assertFalse(self.activo.fsm_instance_id)

    def test_06_ensure_creates_the_instance_once(self):
        lead = self.env['crm.lead'].create(
            {'name': 'una sola vez', 'definition_id': self.definicion.id})
        primera = lead._ensure_fsm_instance()
        self.assertEqual(lead._ensure_fsm_instance(), primera)

    def test_07_ensure_without_definition_says_so(self):
        with self.assertRaises(UserError):
            self.sin_fsm._ensure_fsm_instance()

    def test_08_related_fields_read_through_the_link(self):
        """Las vistas siguen pidiendo los mismos nombres al lead."""
        instancia = self.pausado.fsm_instance_id
        instancia.write({'current_state_id': 'n_espera', 'next_node_id': 'n_otro'})
        self.assertEqual(self.pausado.fsm_state, 'paused')
        self.assertEqual(self.pausado.current_state_id, 'n_espera')
        self.assertEqual(self.pausado.next_node_id, 'n_otro')
        # ``debug_mode`` es el único que se escribe desde el lead.
        self.pausado.debug_mode = 'step_by_step'
        self.assertEqual(instancia.debug_mode, 'step_by_step')

    def test_09_assigning_a_production_bot_starts_the_workflow(self):
        bot = self.env['crm.bot'].create({'name': 'Bot productivo'})
        # El bot es una fsm.definition por numa_poly; el diagrama se escribe en
        # la base, que es donde el compilador se dispara.
        definicion = bot.fsm_definition_id
        definicion.write({'json_ui_schema': _esquema_minimo(), 'state': 'production'})
        lead = self.env['crm.lead'].create({'name': 'con bot'})
        self.assertFalse(lead.fsm_instance_id)

        lead.bot_id = bot

        self.assertEqual(lead.definition_id, definicion)
        self.assertTrue(lead.fsm_instance_id)
        self.assertEqual(lead.fsm_state, 'running')
        self.assertEqual(lead.current_state_id, 'n_espera')
        self.assertEqual(lead.json_ui_schema, definicion.json_ui_schema)

    def test_10_start_action_refuses_twice(self):
        definicion = self.env['fsm.definition'].create({
            'name': 'Bot manual', 'json_ui_schema': _esquema_minimo()})
        lead = self.env['crm.lead'].create(
            {'name': 'arranque manual', 'definition_id': definicion.id})
        lead.action_start_fsm()
        self.assertEqual(lead.fsm_state, 'running')
        with self.assertRaises(UserError):
            lead.action_start_fsm()
