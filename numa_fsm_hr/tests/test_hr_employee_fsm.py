# -*- coding: utf-8 -*-
"""
The employee and their FSM instance: the explicit link, the ``has_fsm`` search,
and the views that show the state.

Up to 18.0 the employee inherited ``fsm.instance`` and *was* the instance. In
20.0 they have one: ``fsm_instance_id``. These tests pin down what the change
must not break -the same field names in the views, the same filter- and what can
now be stated: that an employee exists without a workflow, and that the instance
is created once.

The module could not be installed in 18.0 either: the form inherited with a
selector by ``string`` (Odoo forbids that since 17); the search inherited from
``hr.view_employee_search``, which is ``hr.view_employee_filter`` in 18, and
anchored on a ``my_employees`` filter that does not exist. ``has_fsm`` was
computed without a ``search`` method, and the views read ``state`` after numa_fsm
renamed it to ``fsm_state``.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


def _esquema_minimo():
    """A two-node diagram: it starts and then waits in a state."""
    return {
        'nodes': [
            {'id': 'n_start', 'type': 'start', 'label': 'Start', 'code': ''},
            {'id': 'n_espera', 'type': 'state', 'label': 'Waiting'},
        ],
        'connections': [
            {'fromNodeId': 'n_start', 'fromPortName': '__default__', 'toNodeId': 'n_espera'},
        ],
    }


@tagged('post_install', '-at_install')
class TestHrEmployeeFsm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.definicion = cls.env['fsm.definition'].create({'name': 'Employee bot'})
        Employee = cls.env['hr.employee']
        cls.activo = Employee.create({'name': 'fsm running', 'definition_id': cls.definicion.id})
        cls.pausado = Employee.create({'name': 'fsm paused', 'definition_id': cls.definicion.id})
        cls.terminado = Employee.create({'name': 'fsm ended', 'definition_id': cls.definicion.id})
        cls.sin_fsm = Employee.create({'name': 'no fsm'})
        for empleado, estado in ((cls.activo, 'running'), (cls.pausado, 'paused'),
                                 (cls.terminado, 'ended')):
            empleado._ensure_fsm_instance().fsm_state = estado
        cls.todos = cls.activo | cls.pausado | cls.terminado | cls.sin_fsm

    def _buscar(self, dominio):
        return self.env['hr.employee'].search(dominio + [('id', 'in', self.todos.ids)])

    def test_01_compute(self):
        self.assertTrue(self.activo.has_fsm)
        self.assertTrue(self.pausado.has_fsm)
        self.assertFalse(self.terminado.has_fsm)
        self.assertFalse(self.sin_fsm.has_fsm)

    def test_02_search_agrees_with_compute(self):
        con = self.todos.filtered('has_fsm')
        self.assertEqual(con, self.activo | self.pausado)
        sin = self.todos - con
        self.assertEqual(self._buscar([('has_fsm', '=', True)]), con)
        self.assertEqual(self._buscar([('has_fsm', '!=', False)]), con)
        self.assertEqual(self._buscar([('has_fsm', '=', False)]), sin)
        self.assertEqual(self._buscar([('has_fsm', '!=', True)]), sin)

    def test_03_search_covers_an_employee_without_instance(self):
        """With a definition but no instance yet: no active FSM, and the negative
        search still has to find it."""
        pendiente = self.env['hr.employee'].create(
            {'name': 'definition, no instance yet', 'definition_id': self.definicion.id})
        self.todos |= pendiente
        self.assertFalse(pendiente.fsm_instance_id)
        self.assertFalse(pendiente.has_fsm)
        self.assertIn(pendiente, self._buscar([('has_fsm', '=', False)]))
        self.assertNotIn(pendiente, self._buscar([('has_fsm', '=', True)]))

    def test_04_employee_views_validate(self):
        for xmlid in ('numa_fsm_hr.view_hr_employee_form_fsm',
                      'numa_fsm_hr.view_hr_employee_tree_fsm',
                      'numa_fsm_hr.view_hr_employee_search_fsm'):
            self.env.ref(xmlid)._check_xml()
        for xmlid, tipo in (('hr.view_employee_form', 'form'),
                            ('hr.view_employee_filter', 'search')):
            vista = self.env.ref(xmlid)
            self.assertTrue(self.env['hr.employee'].get_view(vista.id, tipo)['arch'])

    def test_05_employee_and_instance_are_two_records(self):
        """The employee is no longer the instance. They are two records with ids
        of their own, and the employee survives if the instance is deleted."""
        instancia = self.activo.fsm_instance_id
        self.assertTrue(instancia)
        self.assertEqual(instancia._name, 'fsm.instance')
        self.assertEqual(instancia.definition_id, self.definicion)
        instancia.unlink()
        self.assertTrue(self.activo.exists())
        self.assertFalse(self.activo.fsm_instance_id)

    def test_06_ensure_creates_the_instance_once(self):
        empleado = self.env['hr.employee'].create(
            {'name': 'only once', 'definition_id': self.definicion.id})
        primera = empleado._ensure_fsm_instance()
        self.assertEqual(empleado._ensure_fsm_instance(), primera)

    def test_07_ensure_without_definition_says_so(self):
        with self.assertRaises(UserError):
            self.sin_fsm._ensure_fsm_instance()

    def test_08_related_fields_read_through_the_link(self):
        """The views still ask the employee for the same names."""
        instancia = self.pausado.fsm_instance_id
        instancia.write({'current_state_id': 'n_espera', 'next_node_id': 'n_otro'})
        self.assertEqual(self.pausado.fsm_state, 'paused')
        self.assertEqual(self.pausado.current_state_id, 'n_espera')
        self.assertEqual(self.pausado.next_node_id, 'n_otro')
        # ``debug_mode`` is the only one written from the employee.
        self.pausado.debug_mode = 'step_by_step'
        self.assertEqual(instancia.debug_mode, 'step_by_step')

    def test_09_assigning_a_production_bot_starts_the_workflow(self):
        bot = self.env['hr.bot'].create({'name': 'Production bot'})
        # The bot is an fsm.definition through numa_poly; the diagram is written
        # on the base, which is where the compiler fires.
        definicion = bot.fsm_definition_id
        definicion.write({'json_ui_schema': _esquema_minimo(), 'state': 'production'})
        empleado = self.env['hr.employee'].create({'name': 'with a bot'})
        self.assertFalse(empleado.fsm_instance_id)

        empleado.bot_id = bot

        self.assertEqual(empleado.definition_id, definicion)
        self.assertTrue(empleado.fsm_instance_id)
        self.assertEqual(empleado.fsm_state, 'running')
        self.assertEqual(empleado.current_state_id, 'n_espera')
        self.assertEqual(empleado.json_ui_schema, definicion.json_ui_schema)

    def test_10_start_action_refuses_twice(self):
        definicion = self.env['fsm.definition'].create({
            'name': 'Manual bot', 'json_ui_schema': _esquema_minimo()})
        empleado = self.env['hr.employee'].create(
            {'name': 'manual start', 'definition_id': definicion.id})
        empleado.action_start_fsm()
        self.assertEqual(empleado.fsm_state, 'running')
        with self.assertRaises(UserError):
            empleado.action_start_fsm()

    def test_11_the_bot_menu_action_opens(self):
        """``view_mode`` said ``tree``, which stopped being a view type in 17.0.

        Nothing validates it on install -``ir.actions.act_window`` does not check
        the contents of ``view_mode``- so the action installed whole and failed
        only when somebody opened the menu."""
        accion = self.env.ref('numa_fsm_hr.action_hr_bot')
        modos = accion.view_mode.split(',')
        self.assertNotIn('tree', modos)
        self.env['hr.bot'].get_views([(False, modo) for modo in modos])
