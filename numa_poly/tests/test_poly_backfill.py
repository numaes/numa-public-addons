# -*- coding: utf-8 -*-
"""
Backfilling the polymorphic rows that pre-existing records are missing.

Installing a polymorphic module on a populated database leaves every existing record
without its base rows. The symptom people report is a MissingError on read, but the two
quiet failures are the dangerous ones: a search on a base field returns nothing, and a
write to one is accepted and discarded. Neither announces itself.
"""
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestPolyBackfill(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Task = self.env['project.task']
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Node = self.env['numa.planning.node']
        self.project = self.env['project.project'].create({'name': 'Backfill Project'})

    def _orphan(self, tasks):
        """Strip the polymorphic rows, leaving what a pre-existing record looks like."""
        self.env.flush_all()
        self.env.cr.execute(
            "DELETE FROM numa_planning_node WHERE id IN %s", (tuple(tasks.ids),))
        self.env.cr.execute(
            "DELETE FROM ir_poly_base WHERE id IN %s", (tuple(tasks.ids),))
        self.env.invalidate_all()
        return tasks

    def _orphan_task(self, **values):
        """A task whose polymorphic rows have been removed, as a legacy row would be."""
        task = self.Task.create(dict({'name': 'Legacy', 'project_id': self.project.id},
                                     **values))
        return self._orphan(task)

    def _base_row_exists(self, task):
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (task.id,))
        return bool(self.env.cr.fetchone()[0])

    # ------------------------------------------------------------------
    def test_01_a_row_without_its_base_is_broken_before_the_backfill(self):
        """The state the backfill exists to repair."""
        task = self._orphan_task()
        self.assertFalse(self._base_row_exists(task))
        self.assertEqual(
            self.Task.search_count([('id', '=', task.id),
                                    ('pln_constraint_type', '!=', False)]), 0,
            "A search on a base field silently misses the record.")

    def test_02_backfill_creates_the_missing_rows(self):
        task = self._orphan_task()

        created = self.Task._poly_backfill_base_rows()

        self.assertTrue(self._base_row_exists(task))
        self.assertGreaterEqual(created.get('numa.planning.node', 0), 1)
        self.env.invalidate_all()
        self.assertTrue(self.Node.browse(task.id).exists())

    def test_03_the_record_becomes_readable_and_searchable(self):
        task = self._orphan_task()
        self.Task._poly_backfill_base_rows()
        self.env.invalidate_all()

        # Reading a base-only field no longer raises.
        self.assertEqual(task.pln_constraint_type, 'asap')
        # And the record stops being invisible to a search on one.
        self.assertEqual(
            self.Task.search_count([('id', '=', task.id),
                                    ('pln_constraint_type', '=', 'asap')]), 1)

    def test_04_declared_defaults_are_applied(self):
        """Defaults come from the ORM, not from poking at Field.default."""
        task = self._orphan_task()
        self.Task._poly_backfill_base_rows()
        self.env.invalidate_all()

        self.assertEqual(task.pln_constraint_type, 'asap')
        self.assertTrue(task.pln_allow_split,
                        "pln_allow_split defaults to True on a new node.")

    def test_05_same_named_columns_are_copied_from_the_record(self):
        """This is what keeps a NOT NULL column like `name` satisfied."""
        task = self._orphan_task(name='Legacy with a name')
        self.Task._poly_backfill_base_rows()
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT name FROM numa_planning_node WHERE id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 'Legacy with a name')

    def test_06_backfilled_records_are_recorded_for_review(self):
        task = self._orphan_task()
        self.Task._poly_backfill_base_rows()

        entry = self.env['numa.poly.backfill'].search(
            [('res_model', '=', 'project.task'), ('res_id', '=', task.id)])
        self.assertEqual(len(entry), 1,
                         "The migration must say which records it guessed values for.")
        self.assertTrue(entry.backfilled_on)
        self.assertTrue(entry.post_pending,
                        "Post-processing is deferred, so it starts pending.")
        self.assertFalse(entry.reviewed)
        action = entry.action_open_record()
        self.assertEqual(action['res_model'], 'project.task')
        self.assertEqual(action['res_id'], task.id)

    def test_07_backfill_is_idempotent(self):
        task = self._orphan_task()
        first = self.Task._poly_backfill_base_rows()
        second = self.Task._poly_backfill_base_rows()

        self.assertGreaterEqual(first.get('numa.planning.node', 0), 1)
        self.assertEqual(second.get('numa.planning.node', 0), 0,
                         "Re-running must not insert anything a second time.")
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_08_records_that_already_have_their_rows_are_untouched(self):
        healthy = self.Task.create({'name': 'Healthy', 'project_id': self.project.id})
        healthy.pln_constraint_type = 'alap'
        self.env.flush_all()

        self.Task._poly_backfill_base_rows()
        self.env.invalidate_all()

        self.assertEqual(healthy.pln_constraint_type, 'alap',
                         "The backfill must never overwrite real data.")

    def test_09_the_values_hook_can_carry_legacy_data_across(self):
        task = self._orphan_task(allocated_hours=12.0)
        self.Task._poly_backfill_base_rows()
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT pln_effort_hours FROM numa_planning_node WHERE id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 12.0,
                         "numa_planning_project maps allocated_hours onto the node.")

    def test_10_pending_post_processing_runs_and_clears(self):
        # Create both, wire the dependency, and only then strip the polymorphic rows:
        # orphaning one at a time would leave the second task pointing its planning root
        # at a node that no longer exists.
        first = self.Task.create({'name': 'Predecessor', 'project_id': self.project.id})
        second = self.Task.create({'name': 'Successor', 'project_id': self.project.id,
                                   'depend_on_ids': [(6, 0, [first.id])]})
        self.env.flush_all()
        self.env['numa.planning.link'].search(
            [('target_node_id', '=', second.id)]).unlink()
        self._orphan(first | second)

        self.Task._poly_backfill_base_rows()
        processed = self.env['ir.poly_base']._cron_poly_backfill_pending()

        self.assertGreaterEqual(processed, 2)
        self.assertTrue(
            self.env['numa.planning.link'].search(
                [('source_node_id', '=', first.id), ('target_node_id', '=', second.id)]),
            "Task dependencies must become planning links.")
        self.assertEqual(self.env['numa.poly.backfill'].search_count([
            ('res_model', '=', 'project.task'),
            ('res_id', 'in', [first.id, second.id]),
            ('post_pending', '=', True),
        ]), 0, "The pending flag must be cleared.")

    def test_11_the_sweep_only_touches_records_of_its_own_concrete_model(self):
        """
        A polymorphic record has a row in every table of its chain. Scoping the pending
        flag by concrete model is what stops the first model to boot from consuming it
        and leaving the model that knows how to finish the job with nothing to do.
        """
        task = self._orphan_task()
        self.Task._poly_backfill_base_rows()

        # The base model must not claim the concrete model's pending work.
        self.assertEqual(self.Node._poly_backfill_run_pending(), 0)
        self.assertTrue(self.env['numa.poly.backfill'].search([
            ('res_model', '=', 'project.task'), ('res_id', '=', task.id),
        ]).post_pending, "The flag must survive an unrelated model's sweep.")

        self.assertGreaterEqual(self.Task._poly_backfill_run_pending(), 1)
