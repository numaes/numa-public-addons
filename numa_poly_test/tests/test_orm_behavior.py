# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class TestPolyOrmBehavior(TransactionCase):
    """
    Test suite for basic ORM behavior of polymorphic models.
    Validates creation, search, write, and deletion across hierarchies.
    """

    def test_01_single_behavior_create(self):
        """Validate that creating a test.poly.project record correctly creates the behavior.a record."""
        project = self.env['test.poly.project'].create({
            'name': 'Project Alpha',
            'field_a': 'Behavior A Value'
        })
        self.assertTrue(project.behavior_a_id, "The behavior A Many2one should have been populated.")
        self.assertEqual(project.behavior_a_id.id, project.id, "The records must share the same ID.")
        
        behavior_a = self.env['test.poly.behavior.a'].browse(project.id)
        self.assertTrue(behavior_a.exists(), "The physical record in behavior.a must exist.")
        self.assertEqual(behavior_a.field_a, 'Behavior A Value', "The injected field's value is not correct.")

    def test_02_multi_behavior_create(self):
        """Validate the creation of multiple behaviors sharing the same ID."""
        project = self.env['test.poly.project'].create({
            'name': 'Project Beta',
            'field_a': 'Injected A',
            'field_b': 42
        })
        self.assertEqual(project.behavior_a_id.id, project.id)
        self.assertEqual(project.behavior_b_id.id, project.id)
        
        behavior_a = self.env['test.poly.behavior.a'].browse(project.id)
        behavior_b = self.env['test.poly.behavior.b'].browse(project.id)
        
        self.assertEqual(behavior_a.field_a, 'Injected A')
        self.assertEqual(behavior_b.field_b, 42)

    def test_03_search_on_injected_field(self):
        """Critical test: search on injected fields."""
        Project = self.env['test.poly.project']
        Project.create({'name': 'P1', 'field_a': 'FindMe'})
        Project.create({'name': 'P2', 'field_a': 'Other'})
        Project.create({'name': 'P3', 'field_a': 'FindMe'})

        found = Project.search([('field_a', '=', 'FindMe')])
        self.assertEqual(len(found), 2, "The search on an injected field should return 2 records.")
        self.assertCountEqual(found.mapped('name'), ['P1', 'P3'])

    def test_04_write_on_injected_field(self):
        """Verify that write() propagates the changes to the base models."""
        project = self.env['test.poly.project'].create({'name': 'UpdateTest', 'field_a': 'OldValue'})
        project.write({'field_a': 'NewValue', 'field_b': 100})
        
        behavior_a = self.env['test.poly.behavior.a'].browse(project.id)
        behavior_b = self.env['test.poly.behavior.b'].browse(project.id)
        
        self.assertEqual(behavior_a.field_a, 'NewValue')
        self.assertEqual(behavior_b.field_b, 100)

    def test_05_unlink_cascades_correctly(self):
        """Verify that deletion propagates to every base."""
        project = self.env['test.poly.project'].create({'name': 'DeleteTest', 'field_a': 'A', 'field_b': 1})
        p_id = project.id
        
        # Verify existence
        self.assertTrue(self.env['test.poly.behavior.a'].browse(p_id).exists())
        self.assertTrue(self.env['test.poly.behavior.b'].browse(p_id).exists())
        
        project.unlink()
        
        # Verify deletion
        self.assertFalse(self.env['test.poly.project'].browse(p_id).exists())
        self.assertFalse(self.env['test.poly.behavior.a'].browse(p_id).exists())
        self.assertFalse(self.env['test.poly.behavior.b'].browse(p_id).exists())
