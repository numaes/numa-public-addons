# -*- coding: utf-8 -*-
"""
Backfilling the polymorphic rows that pre-existing records are missing.

Installing a polymorphic module on a populated database leaves every existing record
without its base rows. The symptom people report is a MissingError on read, but the two
quiet failures are the dangerous ones: a search on a base field returns nothing, and a
write to one is accepted and discarded. Neither announces itself.
"""
from odoo.tests import tagged, TransactionCase

from ..models.poly import _POLY_LEAF_COLUMNS as _poly_leaf_columns_cache


@tagged('post_install', '-at_install')
class TestPolyBackfill(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Task = self.env['project.task']
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Node = self.env['numa.planning.node']
        self.project = self.env['project.project'].create({'name': 'Backfill Project'})
        self._reopen_pairs()

    def _reopen_pairs(self):
        """
        Put project.task back in the state the migration is for.

        The suite runs after installation, by which point the pairs are closed and the
        backfill deliberately refuses to scan them again. Clearing them is how a test
        says "a module has just added this base to a model that already holds records" —
        the only situation in which reconstruction happens at all.
        """
        self.env['numa.poly.backfill.pair'].sudo().search(
            [('concrete_model', '=', 'project.task')]).unlink()

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

    def _shadow_column(self, value=None):
        """
        Give project_task a physical `pln_constraint_type` column, as databases
        migrated from older versions of the bridge actually have.

        The DDL rolls back with the test transaction. It is created here rather than
        skipped over because the rule it exercises is what a real customer database
        depends on: without it every migrated task came out with no scheduling
        constraint instead of ASAP.
        """
        self.env.cr.execute(
            "ALTER TABLE project_task ADD COLUMN IF NOT EXISTS pln_constraint_type varchar")
        # The column cache is module-level and outlives the transaction that rolls the
        # DDL back, so it has to be dropped on the way in *and* on the way out — a stale
        # entry makes every later test SELECT a column that no longer exists.
        _poly_leaf_columns_cache.pop('project_task', None)
        self.addCleanup(_poly_leaf_columns_cache.pop, 'project_task', None)
        task = self.Task.create({'name': 'Shadowed', 'project_id': self.project.id})
        self.env.flush_all()
        if value is not None:
            self.env.cr.execute(
                "UPDATE project_task SET pln_constraint_type = %s WHERE id = %s",
                (value, task.id))
        self.env.cr.execute("DELETE FROM numa_planning_node WHERE id = %s", (task.id,))
        self.env.cr.execute("DELETE FROM ir_poly_base WHERE id = %s", (task.id,))
        self.env.invalidate_all()
        return task

    def _node_constraint(self, task):
        self.env.cr.execute(
            "SELECT pln_constraint_type FROM numa_planning_node WHERE id = %s",
            (task.id,))
        row = self.env.cr.fetchone()
        return row[0] if row else None

    def test_05b_an_empty_concrete_column_does_not_beat_the_default(self):
        """Copying a NULL used to silently drop the default the model declares."""
        task = self._shadow_column()
        self.Task._poly_backfill_base_rows()
        self.assertEqual(self._node_constraint(task), 'asap')

    def test_05c_a_filled_concrete_column_wins_over_the_default(self):
        """The other direction: real data must not be replaced by a default."""
        task = self._shadow_column(value='alap')
        self.Task._poly_backfill_base_rows()
        self.assertEqual(self._node_constraint(task), 'alap')

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

@tagged('post_install', '-at_install')
class TestPolyMissingBaseIsSurvivable(TransactionCase):
    """
    Even with the migration in place there will always be rows created outside the ORM.
    Neither a read nor a write may fail quietly on one.
    """

    def setUp(self):
        super().setUp()
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Task = self.env['project.task']
        self.project = self.env['project.project'].create({'name': 'Survivable'})

    def _orphan_task(self, **values):
        task = self.Task.create(dict({'name': 'Legacy', 'project_id': self.project.id},
                                     **values))
        self.env.flush_all()
        self.env.cr.execute("DELETE FROM numa_planning_node WHERE id = %s", (task.id,))
        self.env.cr.execute("DELETE FROM ir_poly_base WHERE id = %s", (task.id,))
        self.env.invalidate_all()
        return task

    def test_01_reading_a_base_field_answers_the_default(self):
        task = self._orphan_task()
        # Used to raise MissingError and take the whole page down with it.
        self.assertEqual(task.pln_constraint_type, 'asap')
        self.assertTrue(task.pln_allow_split)

    def test_02_reading_does_not_invent_the_row(self):
        """A read must stay a read: no write, no transaction surprise."""
        task = self._orphan_task()
        task.pln_constraint_type
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_03_writing_a_base_field_materialises_the_row(self):
        task = self._orphan_task()

        task.write({'pln_constraint_type': 'alap'})
        self.env.flush_all()
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 1,
                         "The write used to be accepted and discarded.")
        self.assertEqual(task.pln_constraint_type, 'alap',
                         "And the value must actually be there afterwards.")

    def test_04_writing_only_native_fields_creates_nothing(self):
        """The guard must not turn every write into a migration."""
        task = self._orphan_task()

        task.write({'name': 'Renamed'})
        self.env.flush_all()

        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 0)
        self.assertEqual(task.name, 'Renamed')

    def test_05_a_healthy_record_is_unaffected(self):
        task = self.Task.create({'name': 'Healthy', 'project_id': self.project.id})
        task.write({'pln_constraint_type': 'alap'})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(task.pln_constraint_type, 'alap')

@tagged('post_install', '-at_install')
class TestPolyBackfillAtScale(TransactionCase):
    """A table too large to migrate inline must not hold a deployment open."""

    def setUp(self):
        super().setUp()
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Task = self.env['project.task']
        self.Param = self.env['ir.config_parameter'].sudo()
        self.project = self.env['project.project'].create({'name': 'At Scale'})
        self._reopen_pairs()

    def _reopen_pairs(self):
        """
        Put project.task back in the state the migration is for.

        The suite runs after installation, by which point the pairs are closed and the
        backfill deliberately refuses to scan them again. Clearing them is how a test
        says "a module has just added this base to a model that already holds records" —
        the only situation in which reconstruction happens at all.
        """
        self.env['numa.poly.backfill.pair'].sudo().search(
            [('concrete_model', '=', 'project.task')]).unlink()

    def _orphan_tasks(self, count):
        tasks = self.Task.create([
            {'name': 'Legacy %s' % i, 'project_id': self.project.id}
            for i in range(count)])
        self.env.flush_all()
        self.env.cr.execute(
            "DELETE FROM numa_planning_node WHERE id IN %s", (tuple(tasks.ids),))
        self.env.cr.execute(
            "DELETE FROM ir_poly_base WHERE id IN %s", (tuple(tasks.ids),))
        self.env.invalidate_all()
        return tasks

    def test_01_counts_what_is_missing(self):
        self._orphan_tasks(3)
        self.assertGreaterEqual(self.Task._poly_backfill_count_missing(), 3)

    def test_02_the_inline_limit_is_configurable(self):
        self.assertEqual(self.Task._poly_backfill_inline_limit(),
                         self.Task._poly_backfill_inline_limit())
        self.Param.set_param('numa_poly.backfill_inline_limit', '7')
        self.assertEqual(self.Task._poly_backfill_inline_limit(), 7)
        self.Param.set_param('numa_poly.backfill_inline_limit', 'nonsense')
        self.assertGreater(self.Task._poly_backfill_inline_limit(), 0,
                           "A bad parameter must fall back, not crash the upgrade.")

    def test_03_deferred_models_are_remembered_and_forgotten(self):
        self.Task._poly_backfill_defer()
        self.assertIn('project.task',
                      self.Param.get_param('numa_poly.backfill_deferred_models'))
        self.Task._poly_backfill_undefer()
        self.assertNotIn('project.task',
                         self.Param.get_param('numa_poly.backfill_deferred_models') or '')

    def test_04_the_cron_drains_a_deferred_model(self):
        tasks = self._orphan_tasks(4)
        self.Task._poly_backfill_defer()

        self.env['ir.poly_base']._cron_poly_backfill_pending(batch_size=2)

        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id IN %s", (tuple(tasks.ids),))
        self.assertEqual(self.env.cr.fetchone()[0], 4,
                         "The cron must finish what the upgrade deferred.")
        self.assertNotIn('project.task',
                         self.Param.get_param('numa_poly.backfill_deferred_models') or '',
                         "And drop the model once there is nothing left.")

    def test_05_a_batch_limit_leaves_the_rest_for_the_next_run(self):
        tasks = self._orphan_tasks(5)
        self.Task._poly_backfill_base_rows(batch_size=2, limit=2)

        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id IN %s", (tuple(tasks.ids),))
        done = self.env.cr.fetchone()[0]
        self.assertEqual(done, 2, "A limited run must stop where it was told to.")
        self.Task._poly_backfill_base_rows()
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id IN %s", (tuple(tasks.ids),))
        self.assertEqual(self.env.cr.fetchone()[0], 5, "And the rest must follow later.")

@tagged('post_install', '-at_install')
class TestPolyBackfillIsOncePerPair(TransactionCase):
    """
    Reconstruction has a precise trigger: a module adds a base to a model that already
    holds records. For a given (concrete, base) pair that happens once. Later upgrades
    must find the work done and cost nothing; adding a *new* base later reconstructs
    only that pair.
    """

    def setUp(self):
        super().setUp()
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Task = self.env['project.task']
        self.Pair = self.env['numa.poly.backfill.pair']
        self.project = self.env['project.project'].create({'name': 'Once Per Pair'})
        # The suite runs after installation, when the pairs are already closed.
        self.Pair.sudo().search([('concrete_model', '=', 'project.task')]).unlink()

    def _orphan_task(self):
        task = self.Task.create({'name': 'Legacy', 'project_id': self.project.id})
        self.env.flush_all()
        self.env.cr.execute("DELETE FROM numa_planning_node WHERE id = %s", (task.id,))
        self.env.cr.execute("DELETE FROM ir_poly_base WHERE id = %s", (task.id,))
        self.env.invalidate_all()
        return task

    def _pair(self, base_model='numa.planning.node'):
        return self.Pair.search([('concrete_model', '=', 'project.task'),
                                 ('base_model', '=', base_model)], limit=1)

    def test_01_a_completed_pair_is_recorded(self):
        self._orphan_task()
        self.Task._poly_backfill_base_rows()

        pair = self._pair()
        self.assertEqual(pair.state, 'done')
        self.assertTrue(pair.completed_on)
        self.assertGreaterEqual(pair.records_created, 1)

    def test_02_a_closed_pair_is_not_scanned_again(self):
        """
        The point of recording the pair: a later upgrade must not re-do a one-off event.
        A record orphaned afterwards is deliberately *not* repaired here — create()
        maintains new records, and anything inserted behind the ORM is caught on read
        and on write instead.
        """
        self._orphan_task()
        self.Task._poly_backfill_base_rows()
        self.assertEqual(self._pair().state, 'done')

        late = self._orphan_task()
        created = self.Task._poly_backfill_base_rows()

        self.assertFalse(created.get('numa.planning.node'),
                         "A closed pair must not be scanned again.")
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (late.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_03_a_targeted_repair_ignores_the_pair_state(self):
        """A write onto a record with no base row must still work after the migration."""
        self._orphan_task()
        self.Task._poly_backfill_base_rows()
        late = self._orphan_task()

        late.write({'pln_constraint_type': 'alap'})
        self.env.flush_all()
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (late.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 1)
        self.assertEqual(late.pln_constraint_type, 'alap')

    def test_04_a_targeted_repair_does_not_close_a_pair(self):
        late = self._orphan_task()
        self.Task._poly_backfill_base_rows(only_ids=[late.id])

        self.assertNotEqual(self._pair().state, 'done',
                            "One record repaired says nothing about the rest.")

    def test_05_reopening_a_pair_reconstructs_only_that_one(self):
        """Adding a base later must not drag the bases already done back through it."""
        self._orphan_task()
        self.Task._poly_backfill_base_rows()
        self.assertFalse(self.Task._poly_backfill_pending_pairs())

        # Stand in for a module that has just added this base to the model.
        self._pair().unlink()
        self.assertEqual(self.Task._poly_backfill_pending_pairs(),
                         ['numa.planning.node'])
        self.assertEqual(self._pair('ir.poly_base').state, 'done',
                         "The base that was already done stays done.")

        late = self._orphan_task()
        self.Task._poly_backfill_base_rows()
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (late.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_06_counting_skips_closed_pairs(self):
        """The count that decides inline vs deferred must not price a finished job."""
        self._orphan_task()
        self.Task._poly_backfill_base_rows()
        self.assertEqual(self.Task._poly_backfill_count_missing(), 0)

        self._orphan_task()
        self.assertEqual(self.Task._poly_backfill_count_missing(), 0,
                         "Closed pairs are not re-counted.")
        self.assertGreaterEqual(
            self.Task._poly_backfill_count_missing('numa.planning.node'), 1,
            "But an explicit base can still be asked directly.")
