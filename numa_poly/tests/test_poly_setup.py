# -*- coding: utf-8 -*-
from odoo.tests import tagged, TransactionCase

@tagged('post_install', '-at_install', 'poly_setup')
class TestPolySetup(TransactionCase):

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

    def test_no_stale_stored_entry_from_foreign_def_classes(self):
        """
        Verify that _PolyFieldGuard eliminates stale stored entries at the root.

        Before the guard, Phase-1 MRO injection caused definition classes from dep
        model hierarchies (e.g. NumaPlanningNode for numa.planning.node) to appear in
        project.task's _model_classes__, causing _setup_base to add their fields as
        stored/non-related entries.  _build_poly_fields then had to overwrite them.

        With _PolyFieldGuard active during _setup_base, those foreign def classes see
        an empty _field_definitions, so stale entries are never created.  Every field
        that originated in a foreign def class must be related+non-stored in
        project.task._fields.
        """
        if 'project.task' not in self.env or 'numa.planning.node' not in self.env:
            self.skipTest("project.task or numa.planning.node not in registry")

        from odoo.models import MetaModel
        task_cls = type(self.env['project.task'])

        # Collect dep model names for project.task.
        dep_map = {}
        for base in task_cls.__mro__:
            raw = base.__dict__.get('_depend_models')
            if raw and isinstance(raw, dict):
                dep_map.update(raw)
        if not dep_map:
            self.skipTest("project.task has no _depend_models")

        dep_names = set(dep_map.keys())

        # Gather all def classes from dep registry class MROs whose _name is a dep model.
        foreign_def_cls = set()
        for dep_name in dep_names:
            dep_reg = self.env.registry.get(dep_name)
            if dep_reg is None:
                continue
            for c in type.mro(type(dep_reg)):
                if (
                    isinstance(c, MetaModel)
                    and getattr(c, 'pool', None) is None
                    and getattr(c, '_name', None) in dep_names
                ):
                    foreign_def_cls.add(c)

        # Assert no field from a foreign def class appears as stored/non-related
        # in project.task._fields.
        task_fields = self.env['project.task']._fields
        for fdc in foreign_def_cls:
            fd_list = getattr(fdc, '_field_definitions', []) or []
            for f in fd_list:
                fname = getattr(f, 'name', None)
                if fname is None:
                    continue
                field_in_task = task_fields.get(fname)
                if field_in_task is not None:
                    self.assertFalse(
                        getattr(field_in_task, 'store', False)
                        and not getattr(field_in_task, 'related', None),
                        f"Stale stored/non-related entry for '{fname}' in project.task "
                        f"originated from foreign def class {fdc.__name__}. "
                        f"_PolyFieldGuard should have prevented this."
                    )
