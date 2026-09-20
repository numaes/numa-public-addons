# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class TestPolyAdvancedAPI(TransactionCase):
    """
    Advanced test suite for numa_poly.
    Validates casting to concrete models and performance optimizations (N+1).
    """

    def test_10_as_concrete_model_api(self):
        """Validate the as_concrete_model() method for navigating the hierarchy."""
        # Create a record on the concrete model
        child_a = self.env['test.poly.child.a'].create({
            'base_field': 'Base Data',
            'child_a_field': 'Child Specific'
        })
        child_id = child_a.id
        
        # Get it from the base model
        base_record = self.env['test.poly.base'].browse(child_id)
        self.assertEqual(base_record._name, 'test.poly.base')
        
        # Cast to the concrete model
        concrete = base_record.as_concrete_model()
        self.assertEqual(concrete._name, 'test.poly.child.a')
        self.assertEqual(concrete.id, child_id)
        self.assertEqual(concrete.child_a_field, 'Child Specific')

    def test_11_performance_n_plus_one(self):
        """
        Critical performance test: verifies that there is no N+1 on injected fields.
        It must use prefetching to load the base models' data in a single query.
        """
        Project = self.env['test.poly.project']
        # 1. Create 10 records
        for i in range(10):
            Project.create({
                'name': f'Project {i}',
                'field_a': f'Value {i}'
            })
        
        # 2. Search for every project
        projects = Project.search([('name', 'like', 'Project %')])
        self.assertEqual(len(projects), 10)
        
        # 3. Validate the query count
        # The prefetch should load 'field_a' for every record on the first
        # iteration, not one per record: that is what this measures.
        #
        # The cache has to be emptied before measuring. Without this the values
        # are already in memory from the create, the read never touches the
        # database, and assertQueryCount aborts with "did not detect any
        # queries": the prefetch is not doing too much, nothing was measured.
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            for project in projects:
                # Access the injected field
                val = project.field_a
                self.assertTrue(val.startswith('Value '))
