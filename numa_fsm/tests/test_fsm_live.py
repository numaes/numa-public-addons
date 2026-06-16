# -*- coding: utf-8 -*-
"""
Suite de regresión del motor FSM contra la API VIVA de numa_fsm 18.0.

Los tests viejos (test_fsm_instance/templates/timer/form_input) apuntaban a una API muerta
(``text_definition`` / ``onchange_text_definition`` / ``json_logic_schema`` / ``consume_event``)
y daban 22 errores. La API viva es: ``fsm.definition.json_ui_schema`` → compila a
``json_compiled_definition`` (nodes start|state|transition|end + connections) → ``fsm.instance``
con ``start()`` / ``_process_event_sync(event)`` / ``current_state_id`` / ``instance_variables``.

Acá se ejercita el motor de punta a punta con un workflow self-contained (el código de las
transiciones usa sólo ``set_outcome`` + ``variables``, sin métodos de modelo externos).
"""

import json

from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


def _schema():
    """Workflow de aprobación con loop: start → waiting →(approve|reject|increment)."""
    return {
        'nodes': [
            {'id': 'start', 'type': 'start', 'label': 'Start',
             'code': "variables['log'] = ['started']\nset_outcome('__default__')"},
            {'id': 'waiting', 'type': 'state', 'label': 'Waiting',
             'events': [{'name': 'approve'}, {'name': 'reject'}, {'name': 'increment'}]},
            {'id': 'do_approve', 'type': 'transition', 'label': 'Approve',
             'code': ("variables['log'] = variables.get('log', []) + ['approved']\n"
                      "variables['result'] = variables.get('event', {}).get('by', 'unknown')\n"
                      "set_outcome('ok')")},
            {'id': 'do_reject', 'type': 'transition', 'label': 'Reject',
             'code': "set_outcome('ok')"},
            {'id': 'do_increment', 'type': 'transition', 'label': 'Increment',
             'code': "variables['count'] = variables.get('count', 0) + 1\nset_outcome('ok')"},
            {'id': 'do_bad', 'type': 'transition', 'label': 'Bad outcome',
             'code': "set_outcome('inexistente')"},
            {'id': 'approved', 'type': 'end', 'label': 'Approved'},
            {'id': 'rejected', 'type': 'end', 'label': 'Rejected'},
        ],
        'connections': [
            {'fromNodeId': 'start', 'fromPortName': '__default__', 'toNodeId': 'waiting'},
            {'fromNodeId': 'waiting', 'fromPortName': 'approve', 'toNodeId': 'do_approve'},
            {'fromNodeId': 'waiting', 'fromPortName': 'reject', 'toNodeId': 'do_reject'},
            {'fromNodeId': 'waiting', 'fromPortName': 'increment', 'toNodeId': 'do_increment'},
            {'fromNodeId': 'do_approve', 'fromPortName': 'ok', 'toNodeId': 'approved'},
            {'fromNodeId': 'do_reject', 'fromPortName': 'ok', 'toNodeId': 'rejected'},
            {'fromNodeId': 'do_increment', 'fromPortName': 'ok', 'toNodeId': 'waiting'},
            {'fromNodeId': 'do_bad', 'fromPortName': 'ok', 'toNodeId': 'approved'},
        ],
    }


@tagged('post_install', '-at_install')
class TestFsmLive(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.definition = cls.env['fsm.definition'].create({
            'name': 'Test Live Workflow', 'json_ui_schema': _schema(),
        })

    def _new_instance(self):
        return self.env['fsm.instance'].create({'definition_id': self.definition.id})

    # ---------------------------------------------------------------- #
    # Compilación.                                                      #
    # ---------------------------------------------------------------- #
    def test_compile_produces_compiled_definition(self):
        """json_ui_schema se compila a json_compiled_definition con start/nodes/outcomes/eventos."""
        comp = json.loads(self.definition.json_compiled_definition or '{}')
        self.assertEqual(comp.get('start_node_id'), 'start')
        nodes = comp.get('nodes', {})
        self.assertEqual(len(nodes), 8)
        # outcome del start apunta al state waiting
        self.assertEqual(nodes['start']['outcomes']['__default__'], 'waiting')
        # los eventos del state resuelven a su transición destino
        evs = {e['name']: e['target_transition_id'] for e in nodes['waiting']['events']}
        self.assertEqual(evs['approve'], 'do_approve')
        self.assertEqual(evs['increment'], 'do_increment')

    # ---------------------------------------------------------------- #
    # Ciclo de vida de la instancia.                                   #
    # ---------------------------------------------------------------- #
    def test_start_reaches_first_state(self):
        inst = self._new_instance()
        self.assertEqual(inst.state, 'init')
        inst.start()
        self.assertEqual(inst.state, 'running')
        self.assertEqual(inst.current_state_id, 'waiting')
        self.assertEqual((inst.instance_variables or {}).get('log'), ['started'])

    def test_start_twice_raises(self):
        inst = self._new_instance()
        inst.start()
        with self.assertRaises(UserError):
            inst.start()

    def test_event_loop_then_approve(self):
        """increment (loop al mismo state) acumula en variables; approve termina y pasa event data."""
        inst = self._new_instance()
        inst.start()
        inst._process_event_sync({'name': 'increment'})
        self.assertEqual(inst.current_state_id, 'waiting')
        self.assertEqual(inst.instance_variables.get('count'), 1)
        inst._process_event_sync({'name': 'increment'})
        self.assertEqual(inst.instance_variables.get('count'), 2)
        inst._process_event_sync({'name': 'approve', 'by': 'tester'})
        self.assertEqual(inst.state, 'ended')
        self.assertEqual(inst.current_state_id, 'approved')
        self.assertEqual(inst.instance_variables.get('result'), 'tester')
        self.assertIn('approved', inst.instance_variables.get('log', []))

    def test_event_reject_ends_other_branch(self):
        inst = self._new_instance()
        inst.start()
        inst._process_event_sync({'name': 'reject'})
        self.assertEqual(inst.state, 'ended')
        self.assertEqual(inst.current_state_id, 'rejected')

    def test_unknown_event_ignored(self):
        """Un evento sin handler en el state no cambia el estado (se loguea y se ignora)."""
        inst = self._new_instance()
        inst.start()
        inst._process_event_sync({'name': 'inexistente'})
        self.assertEqual(inst.state, 'running')
        self.assertEqual(inst.current_state_id, 'waiting')

    def test_event_ignored_when_not_running(self):
        inst = self._new_instance()  # state='init', sin current_state
        inst._process_event_sync({'name': 'approve'})
        self.assertEqual(inst.state, 'init')

    def test_bad_outcome_sets_error_state(self):
        """Una transición cuyo outcome no tiene connection deja la instancia en 'error'."""
        # Reapuntamos el evento 'approve' a la transición do_bad vía una definición dedicada.
        bad_schema = _schema()
        for c in bad_schema['connections']:
            if c['fromNodeId'] == 'waiting' and c['fromPortName'] == 'approve':
                c['toNodeId'] = 'do_bad'
        bad_def = self.env['fsm.definition'].create(
            {'name': 'Bad Outcome WF', 'json_ui_schema': bad_schema})
        inst = self.env['fsm.instance'].create({'definition_id': bad_def.id})
        inst.start()
        inst._process_event_sync({'name': 'approve'})
        self.assertEqual(inst.state, 'error')

    # ---------------------------------------------------------------- #
    # Timers (referencia polimórfica — fsm.instance real).             #
    # ---------------------------------------------------------------- #
    def test_start_and_stop_timer(self):
        inst = self._new_instance()
        inst.start()
        inst.start_timer({'name': 'timeout'}, delay=3600)
        timer = self.env['fsm.timer'].search([
            ('fsm_instance_model', '=', 'fsm.instance'),
            ('fsm_instance_res_id', '=', inst.id), ('name', '=', 'timeout')])
        self.assertEqual(len(timer), 1)
        self.assertEqual(timer.fsm_instance_id, inst)  # backward-compat para fsm.instance real
        inst.stop_timer('timeout')
        self.assertFalse(self.env['fsm.timer'].search([
            ('fsm_instance_model', '=', 'fsm.instance'),
            ('fsm_instance_res_id', '=', inst.id), ('name', '=', 'timeout')]))

    def test_timer_target_instance_resolves(self):
        """El timer resuelve su instancia destino por (modelo, res_id) — la pieza polimórfica
        que permite que un modelo que hereda fsm.instance por prototipo (ej. persona.documento.
        pedido) reciba timers sin romper la FK a fsm_instance. (send_event es async, no se
        ejercita su entrega acá.)"""
        inst = self._new_instance()
        inst.start()
        inst.start_timer({'name': 'increment'}, delay=0)
        timer = self.env['fsm.timer'].search([
            ('fsm_instance_res_id', '=', inst.id), ('name', '=', 'increment')])
        self.assertEqual(len(timer), 1)
        self.assertEqual(timer.fsm_instance_model, 'fsm.instance')
        self.assertEqual(timer._target_instance(), inst)

    def test_independent_instances(self):
        a, b = self._new_instance(), self._new_instance()
        a.start(); b.start()
        a._process_event_sync({'name': 'increment'})
        a._process_event_sync({'name': 'increment'})
        b._process_event_sync({'name': 'reject'})
        self.assertEqual(a.instance_variables.get('count'), 2)
        self.assertEqual(a.current_state_id, 'waiting')
        self.assertEqual(b.state, 'ended')
        self.assertEqual(b.current_state_id, 'rejected')
