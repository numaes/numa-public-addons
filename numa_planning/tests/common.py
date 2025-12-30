# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class TestPlanningCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Create Official Scenario
        cls.scenario_official = cls.env['numa.planning.scenario'].create({
            'name': 'Official Scenario',
            'is_official': True,
            'is_active': True,
        })
        
        # Create Alternative Scenario for Sandbox testing
        cls.scenario_alternative = cls.env['numa.planning.scenario'].create({
            'name': 'Alternative Scenario',
            'is_official': False,
            'is_active': True,
        })

        # Create Test Resource
        cls.resource_test = cls.env['numa.planning.resource'].create({
            'name': 'Test Machine 1',
            'capacity': 1.0,
        })

    def create_planning_node(self, name, **kwargs):
        """Helper method to create a planning node."""
        vals = {
            'name': name,
        }
        vals.update(kwargs)
        return self.env['numa.planning.node'].create(vals)
