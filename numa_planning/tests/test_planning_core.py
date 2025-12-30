# -*- coding: utf-8 -*-
from .common import TestPlanningCommon
from odoo import fields
from datetime import timedelta

class TestPlanningCore(TestPlanningCommon):

    def test_01_node_basic_crud_defaults(self):
        """Test Case A: Basic CRUD & Defaults"""
        node = self.create_planning_node("Standalone Task")
        
        # Check default fields
        self.assertEqual(node.pln_constraint_type, 'asap', "Default constraint should be ASAP")
        self.assertEqual(node.pln_recalc_status, 'clean', "Initial status should be clean")
        
        # Check computed dates (initially empty)
        self.assertFalse(node.pln_calc_start, "pln_calc_start should be empty without allocations")
        self.assertFalse(node.pln_calc_end, "pln_calc_end should be empty without allocations")
        self.assertEqual(node.pln_effort_hours, 0.0, "Effort should be 0.0 without allocations")

    def test_02_node_allocation_sync(self):
        """Test Case B: Node-Allocation Synchronization (The 'Brain' Logic)"""
        node = self.create_planning_node("Task A")
        
        today = fields.Datetime.now()
        tomorrow = today + timedelta(days=1)
        
        # Step 2: Create an allocation for "Task A" linked to the Official Scenario
        allocation = self.env['numa.planning.allocation'].create({
            'node_id': node.id,
            'resource_id': self.resource_test.id,
            'scenario_id': self.scenario_official.id,
            'start_date': today,
            'end_date': tomorrow,
        })
        
        # Step 3 (Reactivity): Assert that "Task A" automatically updated its dates
        # Use almostEqual for datetime if needed, but here exact should work as we passed them
        self.assertEqual(node.pln_calc_start, today, "Node start should sync with official allocation")
        self.assertEqual(node.pln_calc_end, tomorrow, "Node end should sync with official allocation")
        self.assertEqual(node.pln_effort_hours, 24.0, "Effort should match allocation duration")

        # Step 4 (Inverse): Modify "Task A" pln_calc_start (simulate UI drag)
        new_start = today + timedelta(days=2)
        expected_end = tomorrow + timedelta(days=2)
        
        node.pln_calc_start = new_start
        
        # Check that the allocation record in the database shifted its dates accordingly
        self.assertEqual(allocation.start_date, new_start, "Allocation start should shift with Node")
        self.assertEqual(allocation.end_date, expected_end, "Allocation end should shift with Node (delta shift)")

    def test_03_scenarios_isolation(self):
        """Test Case C: Scenarios & Scopes (Professional Isolation)"""
        node = self.create_planning_node("Multi-Scenario Task")
        
        today = fields.Datetime.now()
        tomorrow = today + timedelta(days=1)
        next_week = today + timedelta(days=7)
        next_week_end = next_week + timedelta(days=1)
        
        # Add a reserved allocation (Official Scenario)
        self.env['numa.planning.allocation'].create({
            'node_id': node.id,
            'resource_id': self.resource_test.id,
            'scenario_id': self.scenario_official.id,
            'start_date': today,
            'end_date': tomorrow,
            'pln_state': 'reserved',
        })
        
        # Add a tentative allocation (Alternative Scenario X) with different dates
        self.env['numa.planning.allocation'].create({
            'node_id': node.id,
            'resource_id': self.resource_test.id,
            'scenario_id': self.scenario_alternative.id,
            'start_date': next_week,
            'end_date': next_week_end,
            'pln_state': 'tentative',
        })
        
        # Assertion: Verify that the Node's computed dates only reflect the Official Scenario
        self.assertEqual(node.pln_calc_start, today, "Node should ignore non-official scenario dates")
        self.assertEqual(node.pln_calc_end, tomorrow, "Node should ignore non-official scenario dates")

    def test_04_availability_ledger(self):
        """Test the Advanced Availability Ledger"""
        # Create a maintenance period (High Priority)
        maintenance_start = fields.Datetime.now()
        maintenance_end = maintenance_start + timedelta(hours=2)
        
        self.env['numa.planning.availability.period'].create({
            'resource_id': self.resource_test.id,
            'start_date': maintenance_start,
            'end_date': maintenance_end,
            'pln_type': 'maintenance',
            'pln_efficiency': 0.0,
            'pln_priority': 10,
            'pln_state': 'planned',
        })
        
        # Create a standard shift period (Lower Priority) covering the same time
        shift_start = maintenance_start - timedelta(hours=1)
        shift_end = maintenance_end + timedelta(hours=1)
        
        self.env['numa.planning.availability.period'].create({
            'resource_id': self.resource_test.id,
            'start_date': shift_start,
            'end_date': shift_end,
            'pln_type': 'standard',
            'pln_efficiency': 1.0,
            'pln_priority': 1,
            'pln_state': 'planned',
        })
        
        # Check capability at different times
        # 1. During maintenance (Priority 10 should win)
        cap_during = self.resource_test.get_capability_at(maintenance_start + timedelta(minutes=30))
        self.assertEqual(cap_during, 0.0, "Priority 10 (Maintenance) should override Priority 1 (Shift)")
        
        # 2. Outside maintenance but within shift
        cap_before = self.resource_test.get_capability_at(shift_start + timedelta(minutes=30))
        self.assertEqual(cap_before, 1.0, "Standard shift efficiency should be returned outside maintenance")
        
        # 3. Outside both
        cap_outside = self.resource_test.get_capability_at(shift_end + timedelta(hours=1))
        self.assertEqual(cap_outside, 0.0, "No periods should return 0.0 capability")

    def test_05_cpm_algorithm(self):
        """Test the CPM/PDM Calculation Engine"""
        # Create 3 nodes in a chain: A -> B -> C
        node_a = self.create_planning_node("Node A") # D = 0 by default, let's set it
        node_a.pln_effort_hours = 10.0
        
        node_b = self.create_planning_node("Node B")
        node_b.pln_effort_hours = 20.0
        
        node_c = self.create_planning_node("Node C")
        node_c.pln_effort_hours = 5.0
        
        # Create links (Finish-to-Start)
        self.env['numa.planning.link'].create({
            'source_node_id': node_a.id,
            'target_node_id': node_b.id,
            'link_type': 'fs',
            'lag_amount': 2.0,
        })
        self.env['numa.planning.link'].create({
            'source_node_id': node_b.id,
            'target_node_id': node_c.id,
            'link_type': 'fs',
            'lag_amount': 0.0,
        })
        
        # Run CPM
        node_a.action_pln_compute_cpm()
        
        # Refresh nodes
        node_a.refresh()
        node_b.refresh()
        node_c.refresh()
        
        # Assertions
        # If project starts at T0 (now):
        # A: ES=T0, EF=T10
        # B: ES=EF(A)+2 = T12, EF=T32
        # C: ES=EF(B)+0 = T32, EF=T37
        
        self.assertEqual(node_a.pln_calc_early_start, node_b.pln_calc_early_start - timedelta(hours=12))
        self.assertEqual(node_b.pln_calc_early_start, node_a.pln_calc_early_end + timedelta(hours=2))
        self.assertEqual(node_c.pln_calc_early_start, node_b.pln_calc_early_end)
        
        # In a simple chain, all should be critical (TF=0)
        self.assertTrue(node_a.pln_is_critical)
        self.assertTrue(node_b.pln_is_critical)
        self.assertTrue(node_c.pln_is_critical)
        self.assertEqual(node_a.pln_total_float, 0.0)

    def test_06_cpm_float_and_non_critical(self):
        """Test CPM with parallel paths and floats"""
        # A -> B -> D
        # A -> C -> D
        node_a = self.create_planning_node("A", pln_effort_hours=10)
        node_b = self.create_planning_node("B", pln_effort_hours=20)
        node_c = self.create_planning_node("C", pln_effort_hours=5) # Shorter path
        node_d = self.create_planning_node("D", pln_effort_hours=10)
        
        self.env['numa.planning.link'].create({'source_node_id': node_a.id, 'target_node_id': node_b.id, 'link_type': 'fs'})
        self.env['numa.planning.link'].create({'source_node_id': node_a.id, 'target_node_id': node_c.id, 'link_type': 'fs'})
        self.env['numa.planning.link'].create({'source_node_id': node_b.id, 'target_node_id': node_d.id, 'link_type': 'fs'})
        self.env['numa.planning.link'].create({'source_node_id': node_c.id, 'target_node_id': node_d.id, 'link_type': 'fs'})
        
        node_a.action_pln_compute_cpm()
        
        # Path A-B-D = 10 + 20 + 10 = 40 (Critical)
        # Path A-C-D = 10 + 5 + 10 = 25
        # Float for C = 40 - 25 = 15
        
        self.assertTrue(node_b.pln_is_critical)
        self.assertFalse(node_c.pln_is_critical)
        self.assertEqual(node_c.pln_total_float, 15.0)

    def test_07_cycle_detection(self):
        """Test that cycles raise UserError"""
        node_a = self.create_planning_node("A")
        node_b = self.create_planning_node("B")
        
        self.env['numa.planning.link'].create({'source_node_id': node_a.id, 'target_node_id': node_b.id, 'link_type': 'fs'})
        self.env['numa.planning.link'].create({'source_node_id': node_b.id, 'target_node_id': node_a.id, 'link_type': 'fs'})
        
        with self.assertRaises(UserError):
            node_a.action_pln_compute_cpm()
