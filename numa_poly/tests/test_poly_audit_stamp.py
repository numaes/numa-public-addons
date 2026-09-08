# -*- coding: utf-8 -*-
"""
The shared identity's audit trail advances, and never at another record's expense.

A polymorphic record has two audit trails. The concrete table keeps its own
``write_date``/``write_uid``, which standard Odoo maintains. ``ir_poly_base`` keeps a
second pair for the identity the whole chain shares, and ``_write_multi`` is what should
keep it current.

It did not. The block was guarded by ``hasattr(type(self), '__depends_base_classes')``,
and that attribute is written inside the body of ``PolyBase`` -- so Python mangles it on
assignment while every reader passes an unmangled string literal. Neither spelling is on
any model in the registry, the test was constant ``False``, and every ``ir_poly_base`` row
still carried its creation timestamp.

Turning it on is what makes the second half necessary. The row is addressed by the
record's own id, which is right until the id is not the record's to claim -- and
production carried 560 ``purchase.order.line`` ids already held by a ``project.task`` or a
``conversation.message``. Printing a quotation writes every line
(``purchase.order.line.state`` is a stored related over ``order_id.state``), so an
ordinary print would have rewritten the shared trail of unrelated records.
"""
from odoo.tests import tagged, TransactionCase


OLD = '2001-01-01 00:00:00'


@tagged('post_install', '-at_install')
class TestPolyAuditStamp(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Task = self.env['project.task']
        if not self.Task._poly_get_depend_models():
            self.skipTest("project.task is not polymorphic here")
        self.project = self.env['project.project'].create({'name': 'Audit'})

    def _task(self, name='Audited'):
        task = self.Task.create({'name': name, 'project_id': self.project.id})
        self.env.flush_all()
        return task

    def _age(self, record_id):
        """Push the base row's trail into the past, so a stamp is visible."""
        self.env.cr.execute(
            "UPDATE ir_poly_base SET write_uid = 1, write_date = %s WHERE id = %s",
            (OLD, record_id))
        self.env.invalidate_all()

    def _base_row(self, record_id):
        self.env.cr.execute(
            "SELECT write_uid, write_date FROM ir_poly_base WHERE id = %s", (record_id,))
        return self.env.cr.fetchone()

    def _claim(self, record_id, model_name):
        """Hand the base row to another model, the shape legacy data is already in."""
        self.env.cr.execute(
            "UPDATE ir_poly_base SET concrete_model_id = %s WHERE id = %s",
            (self.env['ir.model']._get_id(model_name), record_id))
        self.env.invalidate_all()

    def test_01_the_shared_trail_advances_on_write(self):
        """The bug the guard was hiding: it never advanced at all."""
        task = self._task()
        self._age(task.id)

        task.write({'name': 'Renamed'})
        self.env.flush_all()

        write_uid, write_date = self._base_row(task.id)
        self.assertEqual(write_uid, self.env.uid,
                         "ir_poly_base must record who last wrote the shared identity")
        self.assertGreater(str(write_date), OLD,
                           "and when -- a row frozen at its creation timestamp is the "
                           "symptom of the mangled-attribute guard coming back")

    def test_02_a_colliding_id_does_not_forge_the_holder_s_trail(self):
        """What turning the stamp on would have caused, had it not been filtered.

        The stamp is skipped rather than misdirected: the colliding record keeps no shared
        trail until it is renumbered, which is honest -- the alternative is a trail that is
        worse than absent because it looks real.
        """
        task = self._task('Colliding')
        self._age(task.id)
        self._claim(task.id, 'res.partner')
        before = self._base_row(task.id)

        task.write({'name': 'Written while colliding'})
        self.env.flush_all()

        self.assertEqual(
            self._base_row(task.id), before,
            "writing a record whose id belongs to another model must leave that "
            "model's write_uid/write_date exactly as they were")
        self.env.invalidate_all()
        self.assertEqual(task.name, 'Written while colliding',
                         "and the write itself must still go through")

    def test_03_a_mixed_batch_stamps_only_what_it_owns(self):
        """Partial ownership is the realistic shape: 560 lines out of 5,359."""
        owned, colliding = self._task('Owned'), self._task('Colliding')
        self._age(owned.id)
        self._age(colliding.id)
        self._claim(colliding.id, 'res.partner')
        before = self._base_row(colliding.id)

        (owned | colliding).write({'name': 'Batch'})
        self.env.flush_all()

        self.assertEqual(self._base_row(owned.id)[0], self.env.uid,
                         "the sound record in the batch is stamped")
        self.assertEqual(self._base_row(colliding.id), before,
                         "the colliding one is not, and neither is its holder")

    def test_04_the_concrete_table_keeps_its_own_trail(self):
        """The stamp must not be mistaken for a replacement of the standard one."""
        task = self._task('Native')
        self.env.cr.execute(
            "UPDATE project_task SET write_date = %s WHERE id = %s", (OLD, task.id))
        self.env.invalidate_all()

        task.write({'name': 'Still native'})
        self.env.flush_all()

        self.env.cr.execute(
            "SELECT write_date FROM project_task WHERE id = %s", (task.id,))
        self.assertGreater(str(self.env.cr.fetchone()[0]), OLD,
                           "project_task.write_date is Odoo's to maintain and must "
                           "still advance")

    def test_05_ownership_is_answered_for_the_whole_chain(self):
        """`_poly_owned_base_ids` is the one query both the stamp and the safety net ask.

        Getting the chain wrong here would either forge trails again or stamp nothing.
        """
        task = self._task('Chain')

        self.assertEqual(self.Task._poly_owned_base_ids([task.id]), [task.id])
        self._claim(task.id, 'res.partner')
        self.assertEqual(self.Task._poly_owned_base_ids([task.id]), [],
                         "a row held by an unrelated model is not this model's to write")
        self.assertEqual(self.Task._poly_owned_base_ids([]), [])
        self.assertEqual(self.Task._poly_owned_base_ids([-1, 0, None]), [],
                         "NewId placeholders and blanks must not reach the query")
