# -*- coding: utf-8 -*-
"""
Two legacy records that hold the same id.

``ir.poly_base`` is one global id space: ``create`` allocates every polymorphic id from
``ir_poly_base_id_seq``, so an id identifies a record across the whole polymorphic
universe. Records that predate the polymorphic module do not come from that sequence —
they come from their own table's — so a ``purchase.order.line`` and a ``res.partner``
routinely hold the same id.

The backfill used to ask only whether *a* base row with that id existed. It could not
tell "this record's row" from "somebody else's row", so the second model to be
reconstructed silently kept none of its own: its rows read as already done, the
``INSERT ... ON CONFLICT DO NOTHING`` was a no-op, and the pair was closed. What the
records were left with is worse than nothing — ``ir_poly_base.concrete_model_id`` then
names the *wrong* model, so anything resolved through a polymorphic base dispatches to
it.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase

from ..models.poly import _poly_base_row_is_usable


@tagged('post_install', '-at_install')
class TestPolyIdCollisions(TransactionCase):

    def setUp(self):
        super().setUp()
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Task = self.env['project.task']
        self.Pair = self.env['numa.poly.backfill.pair'].sudo()
        self.project = self.env['project.project'].create({'name': 'Collisions'})
        self.other_model_id = self.env['ir.model']._get_id('res.partner')

    # -- fixtures ---------------------------------------------------------------

    def _orphan_task(self, claimed=False, **values):
        """A task as it looks before the polymorphic module was installed.

        ``claimed=True`` hands its id to another concrete model as well, which is what a
        second legacy table numbering from 1 does. The two happen in one burst on
        purpose: the safety net now completes an incomplete record the moment anything
        touches it, so a fixture that pauses in between finds its own orphan repaired.
        """
        task = self.Task.create(dict({'name': 'Legacy', 'project_id': self.project.id},
                                     **values))
        self.env.flush_all()
        self.env.cr.execute("DELETE FROM numa_planning_node WHERE id = %s", (task.id,))
        self.env.cr.execute("DELETE FROM ir_poly_base WHERE id = %s", (task.id,))
        if claimed:
            self._claim(task.id)
        self.env.invalidate_all()
        return task

    def _claim(self, record_id, model_id=None):
        """Give the id to another concrete model, as an overlapping legacy row does."""
        self.env.cr.execute(
            "INSERT INTO ir_poly_base (id, concrete_model_id, create_uid, write_uid, "
            "create_date, write_date) VALUES (%s, %s, 1, 1, now(), now())",
            (record_id, model_id or self.other_model_id))
        self.env.invalidate_all()

    def _no_renumbering(self):
        """Have the backfill report collisions instead of resolving them."""
        self.env['ir.config_parameter'].sudo().set_param(
            'numa_poly.renumber_collisions', '0')

    def _reopen_pairs(self, model='project.task'):
        self.Pair.search([('concrete_model', '=', model)]).unlink()

    def _base_rows(self, record_id):
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (record_id,))
        return self.env.cr.fetchone()[0]

    # -- detection --------------------------------------------------------------

    def test_01_a_claimed_id_is_not_a_reconstructed_record(self):
        """The old test — does a row with this id exist? — answers yes, wrongly."""
        task = self._orphan_task(claimed=True)

        self.assertEqual(
            self.Task._poly_backfill_count_colliding('ir.poly_base'), 1,
            "The base row belongs to res.partner, not to this task.")

    def test_02_the_backfill_does_not_pretend_to_have_fixed_it(self):
        self._no_renumbering()
        task = self._orphan_task(claimed=True)
        self._reopen_pairs()

        self.Task._poly_backfill_base_rows()

        self.env.cr.execute(
            "SELECT m.model FROM ir_poly_base b JOIN ir_model m "
            "ON m.id = b.concrete_model_id WHERE b.id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 'res.partner',
                         "Nothing may overwrite the row that is already there.")
        self.assertEqual(self._base_rows(task.id), 0,
                         "And no node row may be built on a foreign id.")

    def test_03_a_blocked_pair_is_not_closed(self):
        self._no_renumbering()
        task = self._orphan_task(claimed=True)
        self._reopen_pairs()

        self.Task._poly_backfill_base_rows()

        pair = self.Pair.search([('concrete_model', '=', 'project.task'),
                                 ('base_model', '=', 'ir.poly_base')])
        self.assertEqual(pair.state, 'blocked',
                         "A pair marked done is a pair never scanned again.")
        self.assertEqual(pair.collisions, 1)

    def test_04_a_record_whose_id_is_free_is_still_reconstructed(self):
        """One blocked record must not strand the rest of the table."""
        self._no_renumbering()
        blocked = self._orphan_task(claimed=True, name='Blocked')
        # In a project of its own: numa_planning_project makes the first task of a
        # project the planning root of the others, and a root that cannot be
        # reconstructed is a foreign key nothing can satisfy — true of the product, not
        # of the backfill this test is about.
        elsewhere = self.env['project.project'].create({'name': 'Elsewhere'})
        healthy = self._orphan_task(name='Healthy', project_id=elsewhere.id)
        self._reopen_pairs()

        self.Task._poly_backfill_base_rows()

        self.assertEqual(self._base_rows(healthy.id), 1)
        self.assertEqual(self._base_rows(blocked.id), 0)

    def test_05_the_census_names_the_two_models(self):
        task = self._orphan_task(claimed=True)

        census = self.env['ir.poly_base']._poly_collision_census()
        entry = [c for c in census if c['concrete_model'] == 'project.task']

        self.assertTrue(entry, "The census must report the model that lost its ids.")
        self.assertIn(task.id, entry[0]['ids'])
        self.assertEqual(entry[0]['claimed_by'].get(task.id), 'res.partner')

    def test_06_a_leaf_may_use_the_rows_of_its_own_bases(self):
        """
        Ownership is not equality. A record owns the rows of every base it sits on, and
        reading those as collisions would condemn each of them to be renumbered away
        from the record they belong to.
        """
        pool = self.env.registry
        self.assertTrue(_poly_base_row_is_usable('project.task', 'numa.planning.node', pool),
                        "A node row under a task's id is that task's own row.")
        self.assertTrue(_poly_base_row_is_usable('project.task', 'project.task', pool))
        self.assertFalse(
            _poly_base_row_is_usable('purchase.order.line', 'project.task', pool),
            "Two models on the same base are still two records.")

        task = self.Task.create({'name': 'Healthy', 'project_id': self.project.id})
        self.env.flush_all()
        self.assertEqual(self.Task._poly_backfill_count_colliding('numa.planning.node'), 0)
        self.assertTrue(task.exists())

    # -- operability ------------------------------------------------------------

    def test_07_writing_to_a_blocked_record_says_what_is_wrong(self):
        """
        A raw ForeignKeyViolation three frames deep is not an answer. The write cannot
        succeed — the row cannot be built — so it must at least name the cause.
        """
        task = self._orphan_task(claimed=True)

        with self.assertRaises(UserError) as caught:
            task.write({'pln_constraint_type': 'alap'})

        message = str(caught.exception)
        self.assertIn('res.partner', message)
        self.assertIn(str(task.id), message)

    # -- renumbering ------------------------------------------------------------

    def test_08_renumbering_frees_the_record_from_the_taken_id(self):
        task = self._orphan_task(claimed=True, name='Renumber me')
        old_id = task.id

        moved = self.Task._poly_renumber_colliding()

        self.assertEqual(list(moved), [old_id])
        new_id = moved[old_id]
        self.assertNotEqual(new_id, old_id)
        self.env.cr.execute("SELECT name FROM project_task WHERE id = %s", (new_id,))
        self.assertEqual(self.env.cr.fetchone()[0], 'Renumber me')
        self.env.cr.execute("SELECT count(*) FROM project_task WHERE id = %s", (old_id,))
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_09_what_pointed_at_the_record_still_does(self):
        parent = self.Task.create({'name': 'Parent', 'project_id': self.project.id})
        child = self.Task.create({'name': 'Child', 'project_id': self.project.id,
                                  'parent_id': parent.id})
        self.env.flush_all()
        self.env.cr.execute("DELETE FROM numa_planning_node WHERE id = %s", (parent.id,))
        self.env.cr.execute("DELETE FROM ir_poly_base WHERE id = %s", (parent.id,))
        self._claim(parent.id)

        moved = self.Task._poly_renumber_colliding()

        self.env.cr.execute("SELECT parent_id FROM project_task WHERE id = %s",
                            (child.id,))
        self.assertEqual(self.env.cr.fetchone()[0], moved[parent.id],
                         "A renumbering that orphans its children is data loss.")

    def test_10_the_renumbered_record_gets_its_polymorphic_rows(self):
        task = self._orphan_task(claimed=True)
        self._reopen_pairs()

        moved = self.Task._poly_renumber_colliding()
        self.Task._poly_backfill_base_rows()

        new_id = moved[task.id]
        self.assertEqual(self._base_rows(new_id), 1)
        self.env.cr.execute(
            "SELECT m.model FROM ir_poly_base b JOIN ir_model m "
            "ON m.id = b.concrete_model_id WHERE b.id = %s", (new_id,))
        self.assertEqual(self.env.cr.fetchone()[0], 'project.task')

    def test_11_a_dry_run_reports_without_moving_anything(self):
        task = self._orphan_task(claimed=True)

        planned = self.Task._poly_renumber_colliding(dry_run=True)

        self.assertEqual(list(planned), [task.id])
        self.env.cr.execute("SELECT count(*) FROM project_task WHERE id = %s", (task.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 1,
                         "A dry run that moves a row is not a dry run.")

    def test_12_nothing_to_renumber_is_not_an_error(self):
        self.Task.create({'name': 'Healthy', 'project_id': self.project.id})
        self.env.flush_all()

        self.assertEqual(self.Task._poly_renumber_colliding(), {})
