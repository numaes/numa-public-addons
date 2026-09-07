# -*- coding: utf-8 -*-
"""
Working with a record whose polymorphic rows were never built.

The transition to a polymorphic model is not instantaneous: a large table is migrated by
a cron over several runs, a failed backfill leaves the rest of the table behind, and rows
created outside the ORM never had the migration applied at all. In between, people keep
using the system. An incomplete record therefore has to stay usable — reads answer the
declared defaults, and anything that needs the row to exist builds it first.

The rule this file exists for: *what makes the repair necessary is the state of the
record, not the names of the fields being written*. A write of a purely native field is
what took production down — ``purchase.order.line.write({'date_planned': ...})`` goes on
to create an allocation pointing at the line's node row, and that row did not exist:

    ForeignKeyViolation: numa_planning_allocation_node_id_fkey
    Key (node_id)=(14764) is not present in table "numa_planning_node"
"""
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestIncompleteRecordsAreUsable(TransactionCase):

    def setUp(self):
        super().setUp()
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Task = self.env['project.task']
        self.project = self.env['project.project'].create({'name': 'Incomplete'})

    def _orphan_task(self, **values):
        task = self.Task.create(dict({'name': 'Legacy', 'project_id': self.project.id},
                                     **values))
        self.env.flush_all()
        self.env.cr.execute("DELETE FROM numa_planning_node WHERE id = %s", (task.id,))
        self.env.cr.execute("DELETE FROM ir_poly_base WHERE id = %s", (task.id,))
        self.env.invalidate_all()
        return task

    def _node_rows(self, record_id):
        self.env.cr.execute(
            "SELECT count(*) FROM numa_planning_node WHERE id = %s", (record_id,))
        return self.env.cr.fetchone()[0]

    def test_01_a_write_of_a_native_field_completes_the_record(self):
        """
        This is the production crash. The write itself needs nothing from the base row;
        what follows it does.
        """
        task = self._orphan_task()

        task.write({'name': 'Renamed'})
        self.env.flush_all()

        self.assertEqual(self._node_rows(task.id), 1)
        self.assertEqual(task.name, 'Renamed')

    def test_02_a_read_still_does_not_write(self):
        """A read must stay a read: no write, no transaction surprise, no lock."""
        task = self._orphan_task()

        self.assertEqual(task.pln_constraint_type, 'asap')

        self.assertEqual(self._node_rows(task.id), 0)

    def test_03_referencing_an_incomplete_record_completes_it(self):
        """
        Nobody wrote the task; a third record merely points at its base row. Without the
        row that is a ForeignKeyViolation from inside the other model's create.
        """
        task = self._orphan_task()
        scenario = self.env['numa.planning.scenario'].create({'name': 'Repair'})
        resource = self.env['numa.planning.resource'].create({'name': 'Crew'})

        allocation = self.env['numa.planning.allocation'].create({
            'node_id': task.id,
            'resource_id': resource.id,
            'scenario_id': scenario.id,
            'start_date': '2026-01-01 08:00:00',
            'end_date': '2026-01-02 08:00:00',
        })
        self.env.flush_all()

        self.assertTrue(allocation.exists())
        self.assertEqual(self._node_rows(task.id), 1)

    def test_04_writing_the_reference_afterwards_completes_it_too(self):
        task = self._orphan_task()
        other = self._orphan_task(name='Other')
        scenario = self.env['numa.planning.scenario'].create({'name': 'Repair'})
        resource = self.env['numa.planning.resource'].create({'name': 'Crew'})
        allocation = self.env['numa.planning.allocation'].create({
            'node_id': task.id,
            'resource_id': resource.id,
            'scenario_id': scenario.id,
            'start_date': '2026-01-01 08:00:00',
            'end_date': '2026-01-02 08:00:00',
        })
        self.env.flush_all()

        allocation.write({'node_id': other.id})
        self.env.flush_all()

        self.assertEqual(self._node_rows(other.id), 1)

    def test_05_a_healthy_record_costs_one_lookup(self):
        """
        The guard runs on every write, so what it costs when there is nothing to do is
        part of its design: one indexed lookup on ir.poly_base, and out.
        """
        task = self.Task.create({'name': 'Healthy', 'project_id': self.project.id})
        self.env.flush_all()

        with self.assertQueryCount(__system__=1):
            self.Task._poly_ensure_base_rows(task.ids)

    def test_06_a_finished_migration_does_not_switch_the_guard_off(self):
        """
        Every pair of project.task is closed in a test database, and this record is
        still incomplete — which is the point. A finished migration says the records of
        that moment were completed, not that none can appear afterwards.
        """
        task = self._orphan_task()
        self.assertTrue(self.Task._poly_transition_finished())

        self.Task._poly_ensure_base_rows(task.ids)

        self.assertEqual(self._node_rows(task.id), 1)

    def test_07_a_bulk_write_repairs_every_record_it_touches(self):
        tasks = self._orphan_task(name='One') | self._orphan_task(name='Two')

        tasks.write({'description': '<p>bulk</p>'})
        self.env.flush_all()

        for task in tasks:
            self.assertEqual(self._node_rows(task.id), 1)
