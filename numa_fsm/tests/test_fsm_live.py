# -*- coding: utf-8 -*-
"""
Regression suite of the FSM engine against the LIVE API of numa_fsm 18.0.

The old tests (test_fsm_instance/templates/timer/form_input) targeted a dead API
(``text_definition`` / ``onchange_text_definition`` / ``json_logic_schema`` / ``consume_event``)
and gave 22 errors. The live API is: ``fsm.definition.json_ui_schema`` → compiles to
``json_compiled_definition`` (nodes start|state|transition|end + connections) → ``fsm.instance``
with ``start()`` / ``_process_event_sync(event)`` / ``current_state_id`` / ``instance_variables``.

Here the engine is exercised end to end with a self-contained workflow (the code of the
transitions uses only ``set_outcome`` + ``variables``, without external model methods).
"""

import json

from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


def _schema():
    """Approval workflow with a loop: start → waiting →(approve|reject|increment)."""
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
    # Compilation.                                                     #
    # ---------------------------------------------------------------- #
    def test_compile_produces_compiled_definition(self):
        """json_ui_schema compiles to json_compiled_definition with start/nodes/outcomes/events."""
        comp = json.loads(self.definition.json_compiled_definition or '{}')
        self.assertEqual(comp.get('start_node_id'), 'start')
        nodes = comp.get('nodes', {})
        self.assertEqual(len(nodes), 8)
        # the outcome of the start points to the waiting state
        self.assertEqual(nodes['start']['outcomes']['__default__'], 'waiting')
        # the events of the state resolve to their target transition
        evs = {e['name']: e['target_transition_id'] for e in nodes['waiting']['events']}
        self.assertEqual(evs['approve'], 'do_approve')
        self.assertEqual(evs['increment'], 'do_increment')

    # ---------------------------------------------------------------- #
    # Instance life cycle.                                             #
    # ---------------------------------------------------------------- #
    def test_start_reaches_first_state(self):
        inst = self._new_instance()
        self.assertEqual(inst.fsm_state, 'init')
        inst.start()
        self.assertEqual(inst.fsm_state, 'running')
        self.assertEqual(inst.current_state_id, 'waiting')
        self.assertEqual((inst.instance_variables or {}).get('log'), ['started'])

    def test_start_twice_raises(self):
        inst = self._new_instance()
        inst.start()
        with self.assertRaises(UserError):
            inst.start()

    def test_event_loop_then_approve(self):
        """increment (loop to the same state) accumulates in variables; approve ends and passes
        event data."""
        inst = self._new_instance()
        inst.start()
        inst._process_event_sync({'name': 'increment'})
        self.assertEqual(inst.current_state_id, 'waiting')
        self.assertEqual(inst.instance_variables.get('count'), 1)
        inst._process_event_sync({'name': 'increment'})
        self.assertEqual(inst.instance_variables.get('count'), 2)
        inst._process_event_sync({'name': 'approve', 'by': 'tester'})
        self.assertEqual(inst.fsm_state, 'ended')
        self.assertEqual(inst.current_state_id, 'approved')
        self.assertEqual(inst.instance_variables.get('result'), 'tester')
        self.assertIn('approved', inst.instance_variables.get('log', []))

    def test_event_reject_ends_other_branch(self):
        inst = self._new_instance()
        inst.start()
        inst._process_event_sync({'name': 'reject'})
        self.assertEqual(inst.fsm_state, 'ended')
        self.assertEqual(inst.current_state_id, 'rejected')

    def test_unknown_event_ignored(self):
        """An event with no handler in the state does not change the state (it is logged and
        ignored)."""
        inst = self._new_instance()
        inst.start()
        inst._process_event_sync({'name': 'inexistente'})
        self.assertEqual(inst.fsm_state, 'running')
        self.assertEqual(inst.current_state_id, 'waiting')

    def test_event_ignored_when_not_running(self):
        inst = self._new_instance()  # state='init', no current_state
        inst._process_event_sync({'name': 'approve'})
        self.assertEqual(inst.fsm_state, 'init')

    def test_bad_outcome_sets_error_state(self):
        """A transition whose outcome has no connection leaves the instance in 'error'."""
        # We re-point the 'approve' event to the do_bad transition via a dedicated definition.
        bad_schema = _schema()
        for c in bad_schema['connections']:
            if c['fromNodeId'] == 'waiting' and c['fromPortName'] == 'approve':
                c['toNodeId'] = 'do_bad'
        bad_def = self.env['fsm.definition'].create(
            {'name': 'Bad Outcome WF', 'json_ui_schema': bad_schema})
        inst = self.env['fsm.instance'].create({'definition_id': bad_def.id})
        inst.start()
        inst._process_event_sync({'name': 'approve'})
        self.assertEqual(inst.fsm_state, 'error')

    # ---------------------------------------------------------------- #
    # Timers (polymorphic reference — real fsm.instance).              #
    # ---------------------------------------------------------------- #
    def test_start_and_stop_timer(self):
        inst = self._new_instance()
        inst.start()
        inst.start_timer({'name': 'timeout'}, delay=3600)
        timer = self.env['fsm.timer'].search([
            ('fsm_instance_model', '=', 'fsm.instance'),
            ('fsm_instance_res_id', '=', inst.id), ('name', '=', 'timeout')])
        self.assertEqual(len(timer), 1)
        self.assertEqual(timer.fsm_instance_id, inst)  # backward-compat for a real fsm.instance
        inst.stop_timer('timeout')
        self.assertFalse(self.env['fsm.timer'].search([
            ('fsm_instance_model', '=', 'fsm.instance'),
            ('fsm_instance_res_id', '=', inst.id), ('name', '=', 'timeout')]))

    def test_timer_target_instance_resolves(self):
        """The timer resolves its target instance by (model, res_id) — the polymorphic piece
        that lets a model which inherits fsm.instance by prototype (e.g. persona.documento.
        pedido) receive timers without breaking the FK to fsm_instance. (send_event is async,
        its delivery is not exercised here.)"""
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
        self.assertEqual(b.fsm_state, 'ended')
        self.assertEqual(b.current_state_id, 'rejected')
