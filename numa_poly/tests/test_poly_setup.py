# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.tests import tagged, TransactionCase
from odoo.addons.numa_poly.models.poly import PolyReference

class PolyBaseModel(models.Model):
    _name = 'test.poly.base'
    _description = 'Test Poly Base'
    _inherit = 'ir.poly_base'
    
    name = fields.Char(string='Name')
    base_field = fields.Char(string='Base Field')

class PolyChildModel(models.Model):
    _name = 'test.poly.child'
    _description = 'Test Poly Child'
    _inherit = 'test.poly.base'
    
    # Simulate what numa_poly does manually for testing Field.setup_related
    # related='test.poly.base.base_field' is what Odoo 18 incorrectly injects
    # when classes are in MRO.
    wrong_related_field = fields.Char(related='test.poly.base.base_field')
    
    _depend_models = {'test.poly.base': 'base_id'}
    base_id = fields.Many2one('test.poly.base')

@tagged('post_install', '-at_install', 'poly_setup')
class TestPolySetup(TransactionCase):
    
    def test_related_path_correction(self):
        """
        Tests that polymorphic 'related' paths pointing to model names
        are correctly redirected to link fields by poly_Field_setup_related.
        """
        # We check the field definition on the model class
        field = self.env['test.poly.child']._fields['wrong_related_field']
        
        # In Odoo 18 without our fix, this would crash or point to 'test.poly.base.base_field'
        # With our fix, it should be redirected to 'base_id.base_field'
        self.assertEqual(field.related, 'base_id.base_field', 
                         "The related path should have been redirected via base_id")
        
    def test_m2m_polymorphic_read(self):
        """
        Test that Many2many fields inherited polimorphically (which are related)
        can be read without SQL errors.
        """
        # This relates to the issue description about pln_required_resource_ids
        # project.task inherits from numa.planning.node.
        # We'll use existing models if available or check project.task specifically
        if 'project.task' in self.env and 'numa.planning.node' in self.env:
            Task = self.env['project.task']
            # Verification of field definition
            field = Task._fields.get('pln_required_resource_ids')
            if field:
                self.assertTrue(field.related, "M2M field from depend_model MUST be related")
                self.assertFalse(field.store, "M2M field from depend_model MUST NOT be stored")
                self.assertIn('planning_node_id', field.related, 
                              "Related path should point through link field (planning_node_id)")

            task = Task.search([('pln_required_resource_ids', '!=', False)], limit=1)
            if not task:
                task = Task.search([], limit=1)
            
            if task:
                # Should not raise "column project_task.pln_required_resource_ids does not exist"
                # or "table project_task_resource_rel does not exist"
                try:
                    # In Odoo 18, we can also check if it's accessed as 'own' field in SQL
                    # but here we just check if it works.
                    task.read(['pln_required_resource_ids'])
                    
                    # More advanced check: ensure it's NOT in the table columns
                    self.env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name='project_task' AND column_name='pln_required_resource_ids'")
                    res = self.env.cr.fetchone()
                    self.assertIsNone(res, "Field pln_required_resource_ids should NOT exist as a column in project_task table")
                    
                except Exception as e:
                    self.fail(f"Reading polymorphic M2M field failed: {e}")

    def test_stale_stored_field_removal(self):
        """
        Tests that if a field is incorrectly injected as stored by Odoo's 
        incremental loader, numa_poly removes it to allow proper redirection.
        """
        # We simulate checking a field that comes from a polymorphic ancestor
        # In this environment, we check project.task.pln_required_resource_ids
        # as it was the reported case.
        if 'project.task' in self.env:
            field = self.env['project.task']._fields.get('pln_required_resource_ids')
            if field:
                # If the fix works, it must NOT be a stored field on project.task
                self.assertTrue(field.related, "Field should have been converted to RELATED")
                self.assertFalse(field.store, "Field should have been converted to NON-STORED")
