# -*- coding: utf-8 -*-
import json

from odoo.addons.numa_fsm.tests.common import TestFSMCommon


class TestFSMDebugSuite(TestFSMCommon):
    """
    Unit tests focused on the Debugging & Observability suite.
    Covers: interception (step), step-over, global circuit breaker, and replay.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure jobs/events are synchronous during tests
        cls.env = cls.env(context=dict(cls.env.context, test_queue_job_no_delay=True))

    def _make_definition(self, name, logic_schema):
        fsmd = self.env["fsm.definition"].create({
            "name": name,
            "json_logic_schema": json.dumps(logic_schema),
        })
        return fsmd

    def _make_instance(self, fsmd, current_state, debug_mode='off'):
        fsmi = self.env["fsm.instance"].create({
            "definition_id": fsmd.id,
            "name": f"inst_{fsmd.name}",
        })
        fsmi.write({
            "state": "running",
            "current_state": current_state,
            "json_instance_values": json.dumps({}),
            "debug_mode": debug_mode,
        })
        return fsmi

    def _simple_logic(self):
        """draft --(verify)-> decision(code outcome='ok') --(ok)-> processing"""
        return {
            "states": {"draft": {}, "processing": {}, "done": {}},
            "transitions": {
                "draft": {
                    "verify": {
                        "code": "outcome = 'ok'",
                        "outcomes": {"ok": "processing"},
                    }
                }
            },
        }

    def test_step_by_step_interception(self):
        """When in debug step mode, events are intercepted and enqueued, state doesn't change."""
        fsmd = self._make_definition("Dbg Intercept", self._simple_logic())
        fsmi = self._make_instance(fsmd, current_state="draft", debug_mode='step')

        # Send event: should be intercepted, not executed
        fsmi.consume_event({"name": "verify"})

        # State must remain the same
        self.assertEqual(fsmi.current_state, "draft", "State changed despite step interception")

        # A pending debug event must exist
        pending = fsmi.pending_debug_event_ids
        self.assertTrue(pending, "Expected a pending debug event")
        self.assertEqual(pending[0].state, 'pending', "Debug event is not pending")

    def test_debug_step_over(self):
        """Step Over processes the oldest pending event once, marking it processed and changing state."""
        fsmd = self._make_definition("Dbg Step Over", self._simple_logic())
        fsmi = self._make_instance(fsmd, current_state="draft", debug_mode='step')

        # Intercept first
        fsmi.consume_event({"name": "verify"})
        self.assertTrue(fsmi.pending_debug_event_ids, "Expected an intercepted event")

        # Step over should process that event and mark it processed
        fsmi.action_debug_step_over()

        # Reload pending list
        fsmi.flush()
        # After step-over there should be no pending (or the oldest should be processed)
        processed_any = any(e.state == 'processed' for e in fsmi.pending_debug_event_ids.with_context(active_test=False))
        self.assertTrue(processed_any or not fsmi.pending_debug_event_ids, "Pending debug event was not processed")

        # Instance should have transitioned to 'processing'
        self.assertEqual(fsmi.current_state, "processing", "Step-over did not execute the transition")

    def test_global_circuit_breaker(self):
        """When execution_policy is pause_all, events are intercepted even if instance debug is off."""
        logic = self._simple_logic()
        fsmd = self._make_definition("Dbg Breaker", logic)
        fsmd.write({"execution_policy": "pause_all"})

        fsmi = self._make_instance(fsmd, current_state="draft", debug_mode='off')

        fsmi.consume_event({"name": "verify"})

        # Should have enqueued a pending debug event
        self.assertTrue(fsmi.pending_debug_event_ids, "Breaker did not intercept the event")
        self.assertEqual(fsmi.pending_debug_event_ids[0].state, 'pending')
        # State must remain unchanged
        self.assertEqual(fsmi.current_state, "draft")

    def test_simulation_replay(self):
        """
        Create a success log and replay it. A new simulation instance should be created
        with is_simulation=True. It restores the pre-event env/state and then executes
        the event, so final state should match the original log's to_state.
        """
        logic = self._simple_logic()
        fsmd = self._make_definition("Dbg Replay", logic)
        fsmi = self._make_instance(fsmd, current_state="draft", debug_mode='trace')
        # Put something in env to verify snapshot restoration
        fsmi.write({"json_instance_values": json.dumps({"k": 1})})

        # Execute once in trace mode to generate a success log
        fsmi.consume_event({"name": "verify"})

        # Find the latest log for this instance
        Log = self.env['fsm.execution.log']
        log = Log.search([('instance_id', '=', fsmi.id)], order='timestamp desc, id desc', limit=1)
        self.assertTrue(log, "Expected an execution log entry in trace mode")

        # Replay
        action = log.action_replay_simulation()
        self.assertEqual(action.get('res_model'), 'fsm.instance')
        new_id = action.get('res_id')
        self.assertTrue(new_id, "Replay did not return a target instance id")

        sim = self.env['fsm.instance'].browse(new_id).exists()
        self.assertTrue(sim, "Simulation instance not found")
        self.assertTrue(sim.is_simulation, "Simulation flag not set on replay instance")

        # After replay, the event is executed immediately; expect final state equals original log's to_state
        self.assertEqual(sim.current_state, log.to_state, "Replay did not reach the same final state")
        # And env should contain restored values used prior to the event (the code doesn't modify env)
        env2 = json.loads(sim.json_instance_values or '{}')
        self.assertEqual(env2.get('k'), 1, "Simulation env was not restored from snapshot")
