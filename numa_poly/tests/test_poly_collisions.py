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
from collections import OrderedDict

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

    def test_07_writing_to_a_blocked_record_still_saves_the_record(self):
        """
        This raised at first, on the reasoning that a write which cannot land should say
        so. In production that meant a purchase order nobody could save, because one of
        its lines was waiting for a migration — a system that stops is worse than one
        whose planning fields on that one line stay empty for an hour. The collision goes
        to the log; the record's own fields are saved.
        """
        task = self._orphan_task(claimed=True)

        task.write({'name': 'Renamed', 'pln_constraint_type': 'alap'})
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(task.name, 'Renamed')
        self.assertEqual(self._base_rows(task.id), 0,
                         "The row still cannot be built on somebody else's id.")

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

    # -- finishing without a person ---------------------------------------------

    def test_13_the_cron_finishes_what_the_install_started(self):
        """
        Nobody can foresee which module will make which model polymorphic on which
        database, so nothing here may depend on somebody knowing to run it. Whatever the
        install could not finish is handed to the cron, and the cron finishes it.
        """
        task = self._orphan_task(claimed=True)
        self._reopen_pairs()
        self.Task._poly_backfill_defer()

        self.env['ir.poly_base']._cron_poly_backfill_pending()

        self.assertNotIn('project.task', self._deferred_models(),
                         "A model with nothing left to do must leave the cron's list.")
        self.assertEqual(self.Task._poly_backfill_count_colliding(), 0)

    def test_14_a_model_it_cannot_finish_stays_on_the_list(self):
        """The other half of the same promise: it does not quietly give up either."""
        self._no_renumbering()
        task = self._orphan_task(claimed=True)
        self._reopen_pairs()
        self.Task._poly_backfill_defer()

        self.env['ir.poly_base']._cron_poly_backfill_pending()

        self.assertIn('project.task', self._deferred_models())

    def _deferred_models(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'numa_poly.backfill_deferred_models') or ''
        return [name for name in param.split(',') if name]

    # -- moving a row that points at itself -------------------------------------

    def test_15_a_record_that_is_its_own_root_moves_in_one_piece(self):
        """
        Postgres applies at most one data-modifying CTE to any given row, silently. A
        planning node is its own `pln_root_id`, so the update of the id and the update of
        the reference landed on the same row and only one of them took — and the
        statement died on the foreign key it had just been told to fix.

        `conversation_message` is the same shape three times over: parent_id,
        reference_id and root_id all point at a message.
        """
        task = self._orphan_task(claimed=True, name='Own root')
        old_id = task.id
        self.env.cr.execute(
            "INSERT INTO ir_poly_base (id, concrete_model_id, create_uid, write_uid, "
            "create_date, write_date) VALUES (%s, %s, 1, 1, now(), now()) "
            "ON CONFLICT (id) DO NOTHING", (old_id + 10 ** 7, self.other_model_id))
        # Give it the node row it would have had, rooted on itself.
        self.env.cr.execute(
            "INSERT INTO numa_planning_node (id, name, create_uid, write_uid, "
            "create_date, write_date, pln_root_id) VALUES (%s, %s, 1, 1, now(), now(), %s)",
            (old_id, 'Own root', old_id))

        moved = self.Task._poly_renumber_colliding([old_id])

        new_id = moved[old_id]
        self.env.cr.execute(
            "SELECT id, pln_root_id FROM numa_planning_node WHERE id = %s", (new_id,))
        self.assertEqual(self.env.cr.fetchone(), (new_id, new_id),
                         "The id and the self-reference must move together.")

    def test_16_two_references_from_one_row_both_move(self):
        """The general case behind it: one row, several columns, one renumbered id.

        `numa_planning_node` gets both its own `id` and a `pln_root_id` rewritten in the
        same statement, which is where the one-CTE-per-row rule bites.
        """
        target = self.Task.create({'name': 'Target', 'project_id': self.project.id})
        follower = self.Task.create({'name': 'Follower', 'project_id': self.project.id,
                                     'parent_id': target.id})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE numa_planning_node SET pln_root_id = %s WHERE id = %s",
            (target.id, follower.id))
        # Now take the id away from it, keeping the node row it already has: that row is
        # the record's own and has to travel with it.
        self.env.cr.execute("DELETE FROM ir_poly_base WHERE id = %s", (target.id,))
        self._claim(target.id)

        moved = self.Task._poly_renumber_colliding([target.id])

        new_id = moved[target.id]
        self.env.cr.execute("SELECT parent_id FROM project_task WHERE id = %s",
                            (follower.id,))
        self.assertEqual(self.env.cr.fetchone()[0], new_id)
        self.env.cr.execute("SELECT pln_root_id FROM numa_planning_node WHERE id = %s",
                            (follower.id,))
        self.assertEqual(self.env.cr.fetchone()[0], new_id,
                         "The reference from another row must move too.")
        self.env.cr.execute("SELECT count(*) FROM numa_planning_node WHERE id = %s",
                            (new_id,))
        self.assertEqual(self.env.cr.fetchone()[0], 1,
                         "And the node row must have come along.")


@tagged('post_install', '-at_install')
class TestPolyBaseFieldNames(TransactionCase):
    """
    Two bases of one polymorphic model providing the same field name.

    Only one of them can be ``model.<name>``; the other is not reachable under it.
    ``conversation.message`` sat on ``digital.event`` (state = new/pending/processed/
    error) and on ``fsm.instance`` (state = init/running/paused/ended/error). The event's
    state won, so every ``message.state == 'init'`` in numa_conversation_fsm compared a
    processing status against an FSM state and did nothing — and Odoo's only comment on
    it was a generic line repeated 219 times that named neither base.

    Reported, not forbidden. A subtype redefining an inherited attribute on purpose is a
    legitimate thing to do; what is not legitimate is doing it by accident and finding
    out months later. So numa_poly says which bases collided and which one won, once, and
    leaves the decision to whoever reads it.
    """

    def _collisions(self):
        from ..models.poly import _poly_collect_depend_models, _POLY_TECHNICAL_FIELDS

        found = []
        for model_name in sorted(self.env.registry.models):
            dep_map = _poly_collect_depend_models(self.env.registry[model_name])
            if len(dep_map) < 2:
                continue
            providers = {}
            for base_name in dep_map:
                base = self.env.get(base_name)
                if base is None:
                    continue
                for fname, field in base._fields.items():
                    if fname in _POLY_TECHNICAL_FIELDS or field.related or field.inherited:
                        continue
                    providers.setdefault(fname, []).append(base_name)
            for fname, owners in sorted(providers.items()):
                if len(owners) > 1:
                    found.append((model_name, fname, owners))
        return found

    def test_01_the_collision_that_started_this_is_gone(self):
        """`fsm.instance.state` became `fsm_state`; nothing must put it back."""
        clashes = [c for c in self._collisions() if c[1] == 'state']
        self.assertFalse(
            clashes,
            "A polymorphic base is claiming the name 'state' again: %s. It is too common "
            "a name for a model whose purpose is to be mixed into others." % (clashes,))

    def test_02_a_collision_is_reported_rather_than_hidden(self):
        """
        The detector must name both bases and the winner. Checked against a synthetic
        pair so the test keeps working once — as now — no real collision is left.
        """
        from ..models import poly

        with self.assertLogs('odoo.addons.numa_poly.models.poly', level='WARNING') as logs:
            poly._POLY_REPORTED_COLLISIONS.clear()
            self.addCleanup(poly._POLY_REPORTED_COLLISIONS.clear)
            poly._poly_report_base_field_collisions(_FakePool())

        message = '\n'.join(logs.output)
        self.assertIn('demo.leaf.state', message)
        self.assertIn('demo.first', message)
        self.assertIn('demo.second', message)
        self.assertIn('demo.first wins', message)

    def test_03_the_same_collision_is_not_repeated_on_every_rebuild(self):
        from ..models import poly

        pool = _FakePool()
        poly._POLY_REPORTED_COLLISIONS.clear()
        self.addCleanup(poly._POLY_REPORTED_COLLISIONS.clear)
        with self.assertLogs('odoo.addons.numa_poly.models.poly', level='WARNING') as first:
            poly._poly_report_base_field_collisions(pool)
        poly._poly_report_base_field_collisions(pool)  # must stay silent

        self.assertEqual(len(first.output), 1)


class _FakeField:
    def __init__(self):
        self.related = None
        self.inherited = False


class _FakeModel:
    _fields = {'state': _FakeField()}


class _FakeLeaf:
    _name = 'demo.leaf'
    _depend_models = OrderedDict([('demo.first', 'first_id'), ('demo.second', 'second_id')])


class _FakePool(dict):
    """The smallest thing the collision report reads: a mapping of model name to class."""

    def __init__(self):
        super().__init__({
            'demo.leaf': _FakeLeaf,
            'demo.first': _FakeModel,
            'demo.second': _FakeModel,
        })
