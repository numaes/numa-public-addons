# -*- coding: utf-8 -*-
"""
What "the concrete model owns this field" means.

A model that becomes polymorphic keeps the fields it declares itself -- shadowing them
with a related-to-base version breaks reads of pre-existing rows and, where the types
differ, crashes registry setup. Ownership is a property of the *declaration*, though,
not of the table: a bridge's earlier version can leave a column behind long after the
data moved to the base, and treating that leftover as ownership makes the field resolve
to two different columns depending on how the registry happened to be built.
"""
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestPolyNoShadowFollowsTheDeclaration(TransactionCase):

    def setUp(self):
        super().setUp()
        if 'numa.planning.node' not in self.env:
            self.skipTest("numa_planning_project is not installed")
        self.Task = self.env['project.task']
        self.env.cr.execute("""
            SELECT count(*) FROM information_schema.columns
             WHERE table_name = 'project_task' AND column_name = 'pln_constraint_type'
        """)
        self.leftover = bool(self.env.cr.fetchone()[0])

    def test_01_project_task_does_not_declare_the_planning_fields(self):
        """The premise: the bridge adds `_depend_models`, not the fields themselves."""
        self.assertNotIn('pln_constraint_type',
                         type(self.Task)._poly_native_field_names())

    def test_02_an_undeclared_base_field_is_related_to_the_base(self):
        """
        Regression: a leftover column used to win here.

        `project_task` still carries `pln_*` columns from before the planning fields
        moved to `numa.planning.node`, and the physical-column probe read that as
        ownership -- but only when the probe's cache happened to be warm, which it is
        during an upgrade and is not on a cold registry load. The same database then
        answered `pln_constraint_type` from `project_task` in one process and from
        `numa_planning_node` in another.
        """
        field = self.Task._fields['pln_constraint_type']

        self.assertFalse(field.store,
                         "A field the concrete model does not declare must not be "
                         "stored on the concrete table.")
        self.assertTrue(field.related,
                        "It must resolve through the link to the base.")
        self.assertTrue(field.related.endswith('.pln_constraint_type'), field.related)

    def test_03_the_search_goes_to_the_base_table(self):
        """Where the previous test's divergence actually bit: reads and searches."""
        query = self.Task._search([('pln_constraint_type', '=', 'asap')])
        sql = str(query.select())

        self.assertIn('numa_planning_node', sql)
        self.assertNotIn('"project_task"."pln_constraint_type"', sql)

    def test_04_a_field_the_model_declares_is_still_kept(self):
        """The rule this replaces must not be weakened: a declared field stays its own."""
        self.assertIn('name', type(self.Task)._poly_native_field_names())
        self.assertTrue(self.Task._fields['name'].store,
                        "project.task declares `name`; poly must not shadow it.")


@tagged('post_install', '-at_install')
class TestUnPuenteConserva_SuPropioCompute(TransactionCase):
    """A field a bridge declares itself keeps its own compute, not a related one.

    The no-shadow rule is decided when the contribution class is generated, and the set
    of "native" names was read from `model_class.mro()` — which only answers for the
    classes already linked into it. A bridge loaded after that pass was not there yet,
    so its declaration was invisible: the contribution generated a related version of
    the field and, sitting lower in the MRO, won.

    `numa_planning_purchase` declares `purchase.order.line.pln_constraint_date` with its
    own compute and inverse, mapping it to `date_planned`. It came out
    `related='planning_node_id.pln_constraint_date'`: the bridge's compute never ran and
    the field read False, so the whole date mapping was dead.
    """

    def setUp(self):
        super().setUp()
        if 'purchase.order.line' not in self.env:
            self.skipTest('purchase is not installed')
        self.Line = self.env['purchase.order.line']
        if 'pln_constraint_date' not in self.Line._fields:
            self.skipTest('numa_planning_purchase is not installed')

    def test_01_el_campo_conserva_el_compute_del_puente(self):
        campo = self.Line._fields['pln_constraint_date']
        self.assertFalse(
            campo.related,
            "the bridge declares this field; poly must not replace it with a related one")
        self.assertEqual(campo.compute, '_compute_pln_constraint_date')
        self.assertEqual(campo.inverse, '_inverse_pln_constraint_date')

    def test_02_un_campo_que_el_puente_no_declara_si_es_related(self):
        """The rule is about what the model declares, not about the prefix."""
        campo = self.Line._fields.get('pln_calc_start')
        if campo is None:
            self.skipTest('pln_calc_start is not on this model')
        self.assertTrue(
            campo.related,
            "a field that only the base declares must reach the record through the base")
