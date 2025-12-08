# -*- coding: utf-8 -*-
import json

from odoo.addons.numa_fsm.tests.common import TestFSMCommon


class TestFSMEngineOutcomes(TestFSMCommon):
    """
    Tests for the new outcome-based FSM engine driven by json_logic_schema.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, test_queue_job_no_delay=True))

    def _make_definition(self, name, logic_schema):
        fsmd = self.env["fsm.definition"].create({
            "name": name,
            "json_logic_schema": json.dumps(logic_schema),
        })
        return fsmd

    def _make_instance(self, fsmd, current_state):
        fsmi = self.env["fsm.instance"].create({
            "definition_id": fsmd.id,
            "name": f"inst_{name if (name := fsmd.name) else 'x'}",
        })
        # Set instance as running in the desired state (bypass legacy start mechanics)
        fsmi.write({
            "state": "running",
            "current_state": current_state,
            "json_instance_values": json.dumps({}),
        })
        return fsmi

    def test_graph_based_transition(self):
        """
        draft --(verify)--> decision(code sets outcome='ok') --(ok)--> processing
        Expect current_state to become 'processing'.
        """
        logic = {
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

        fsmd = self._make_definition("Graph Transition", logic)
        fsmi = self._make_instance(fsmd, current_state="draft")

        fsmi.consume_event({"name": "verify"})

        self.assertEqual(fsmi.current_state, "processing", "FSM did not follow outcome mapping to 'processing'")

    def test_conditional_branching(self):
        """
        Event 'check_score' branches to 'approved' or 'rejected' depending on env['score'].
        """
        code = (
            "if env.get('score', 0) > 10:\n"
            "    outcome = 'pass'\n"
            "else:\n"
            "    outcome = 'fail'\n"
        )
        logic = {
            "states": {"draft": {}, "approved": {}, "rejected": {}},
            "transitions": {
                "draft": {
                    "check_score": {
                        "code": code,
                        "outcomes": {"pass": "approved", "fail": "rejected"},
                    }
                }
            },
        }

        fsmd = self._make_definition("Conditional Branch", logic)

        # Case 1: score <= 10 -> fail -> rejected
        fsmi1 = self._make_instance(fsmd, current_state="draft")
        fsmi1.write({"json_instance_values": json.dumps({"score": 7})})
        fsmi1.consume_event({"name": "check_score"})
        self.assertEqual(fsmi1.current_state, "rejected", "Expected 'rejected' for score <= 10")

        # Case 2: score > 10 -> pass -> approved
        fsmi2 = self._make_instance(fsmd, current_state="draft")
        fsmi2.write({"json_instance_values": json.dumps({"score": 15})})
        fsmi2.consume_event({"name": "check_score"})
        self.assertEqual(fsmi2.current_state, "approved", "Expected 'approved' for score > 10")
