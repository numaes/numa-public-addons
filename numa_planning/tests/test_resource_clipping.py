# -*- coding: utf-8 -*-
from .common import TestPlanningCommon
from odoo import fields
from datetime import timedelta

class TestResourceClipping(TestPlanningCommon):

    def test_01_basic_conflict(self):
        """Test Case A: Basic Conflict (1 vs 1)"""
        # Setup: Resource "User A" (Capacity 1.0)
        resource_a = self.env['numa.planning.resource'].create({
            'name': 'User A',
            'capacity': 1.0,
        })
        
        # Theoretical dates (CPM output)
        base_time = fields.Datetime.now()
        
        # Task 1: Duration 24 hours, CPM Start = base_time
        task1 = self.create_planning_node("Task 1", pln_effort_hours=24.0, pln_calc_early_start=base_time)
        # Task 2: Duration 24 hours, CPM Start = base_time
        task2 = self.create_planning_node("Task 2", pln_effort_hours=24.0, pln_calc_early_start=base_time)
        
        # Both tasks suggest resource_a
        self.env['numa.planning.allocation'].create({
            'node_id': task1.id,
            'resource_id': resource_a.id,
            'scenario_id': self.scenario_official.id,
            'pln_state': 'reserved',
        })
        self.env['numa.planning.allocation'].create({
            'node_id': task2.id,
            'resource_id': resource_a.id,
            'scenario_id': self.scenario_official.id,
            'pln_state': 'reserved',
        })

        # Run Leveling
        task1.action_pln_resource_leveling()

        # Assertion:
        # Task 1 (sorted first if same ES) keeps base_time
        # Task 2 is pushed after task 1 finishes
        self.assertEqual(task1.pln_calc_start, base_time, "Task 1 should keep original start time")
        self.assertEqual(task2.pln_calc_start, task1.pln_calc_end, "Task 2 should be pushed after Task 1")
        
        allocations = self.env['numa.planning.allocation'].search([
            ('node_id', 'in', [task1.id, task2.id]),
            ('scenario_id', '=', self.scenario_official.id)
        ])
        self.assertEqual(len(allocations), 2, "There should be two allocations")
        
        # Check they don't overlap
        a1 = allocations.filtered(lambda a: a.node_id == task1)
        a2 = allocations.filtered(lambda a: a.node_id == task2)
        self.assertTrue(a1.end_date <= a2.start_date or a2.end_date <= a1.start_date, "Allocations should not overlap")

    def test_02_tetris_fit(self):
        """Test Case B: The 'Tetris' Fit"""
        resource_x = self.env['numa.planning.resource'].create({
            'name': 'Machine X',
            'capacity': 1.0,
        })
        
        base_time = fields.Datetime.to_datetime('2025-01-01 08:00:00')
        
        # Task Long: 08:00 - 12:00. Fixed/Locked.
        node_long = self.create_planning_node("Task Long", pln_effort_hours=4.0)
        self.env['numa.planning.allocation'].create({
            'node_id': node_long.id,
            'resource_id': resource_x.id,
            'scenario_id': self.scenario_official.id,
            'start_date': base_time,
            'end_date': base_time + timedelta(hours=4),
            'pln_state': 'reserved',
            'pln_is_locked': True,
        })
        
        # Task Fixed: 14:00 - 18:00. Fixed/Locked.
        node_fixed = self.create_planning_node("Task Fixed", pln_effort_hours=4.0)
        self.env['numa.planning.allocation'].create({
            'node_id': node_fixed.id,
            'resource_id': resource_x.id,
            'scenario_id': self.scenario_official.id,
            'start_date': base_time + timedelta(hours=6),
            'end_date': base_time + timedelta(hours=10),
            'pln_state': 'reserved',
            'pln_is_locked': True,
        })
        
        # Task Fit: Duration 2 hours. CPM ES = 08:00
        node_fit = self.create_planning_node("Task Fit", pln_effort_hours=2.0, pln_calc_early_start=base_time)
        # Assign resource_x to node_fit
        self.env['numa.planning.allocation'].create({
            'node_id': node_fit.id,
            'resource_id': resource_x.id,
            'scenario_id': self.scenario_official.id,
            'pln_state': 'tentative',
        })

        # Run Leveling
        node_fit.action_pln_resource_leveling()

        # Assertion: The engine places "Task Fit" in the gap (12:00 - 14:00)
        expected_start = base_time + timedelta(hours=4)
        expected_end = base_time + timedelta(hours=6)
        self.assertEqual(node_fit.pln_calc_start, expected_start, "Task Fit should start at 12:00")
        self.assertEqual(node_fit.pln_calc_end, expected_end, "Task Fit should end at 14:00")

    def test_03_capacity_efficiency(self):
        """Test Case C: Capacity Check (Efficiency)"""
        # Setup: Resource "Junior" (Efficiency 0.5)
        # We simulate efficiency using the Availability Ledger
        resource_junior = self.env['numa.planning.resource'].create({
            'name': 'Junior',
            'capacity': 1.0,
        })
        
        base_time = fields.Datetime.now()
        
        # Create a period with 0.5 efficiency
        self.env['numa.planning.availability.period'].create({
            'resource_id': resource_junior.id,
            'start_date': base_time - timedelta(days=1),
            'end_date': base_time + timedelta(days=5),
            'pln_efficiency': 0.5,
            'pln_priority': 10,
            'pln_state': 'active',
        })
        
        # Data: Task A (Effort 4 hours)
        task_a = self.create_planning_node("Task A", pln_effort_hours=4.0, pln_calc_early_start=base_time)
        
        # Assign resource
        self.env['numa.planning.allocation'].create({
            'node_id': task_a.id,
            'resource_id': resource_junior.id,
            'scenario_id': self.scenario_official.id,
            'pln_state': 'reserved',
        })

        # Run Leveling
        task_a.action_pln_resource_leveling()

        # Assertion: The resulting allocation has a duration of 8 hours (4h effort / 0.5 efficiency)
        self.assertEqual(task_a.pln_effort_hours, 4.0, "Effort remains 4h")
        duration = (task_a.pln_calc_end - task_a.pln_calc_start).total_seconds() / 3600.0
        self.assertEqual(duration, 8.0, "Real duration should be 8h due to 0.5 efficiency")
