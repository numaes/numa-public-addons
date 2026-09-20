# -*- coding: utf-8 -*-
"""
El empleado y su instancia FSM: el vínculo explícito, la búsqueda por ``has_fsm``
y las vistas que muestran el estado.

Hasta 18.0 el empleado heredaba ``fsm.instance`` y *era* la instancia. En 20.0
tiene una: ``fsm_instance_id``. Estos tests fijan lo que el cambio no debía
romper —los mismos nombres de campo en las vistas, el mismo filtro— y lo que
ahora sí se puede afirmar: que el empleado existe sin workflow y que la
instancia se crea una sola vez.

El módulo además no se podía instalar en 18.0: el form heredaba con un selector
por ``string`` (Odoo lo prohíbe desde la 17); la búsqueda heredaba de
``hr.view_employee_search``, que en 18 es ``hr.view_employee_filter``, y se
anclaba en un filtro ``my_employees`` que no existe. ``has_fsm`` era computado
sin ``search``, y las vistas usaban ``state`` después del renombre a
``fsm_state`` en numa_fsm.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


def _esquema_minimo():
    """Un diagrama de dos nodos: arranca y se queda esperando en un estado."""
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
        cls.definicion = cls.env['fsm.definition'].create({'name': 'Bot de empleados'})
        Employee = cls.env['hr.employee']
        cls.activo = Employee.create({'name': 'fsm activo', 'definition_id': cls.definicion.id})
        cls.pausado = Employee.create({'name': 'fsm pausado', 'definition_id': cls.definicion.id})
        cls.terminado = Employee.create({'name': 'fsm terminado', 'definition_id': cls.definicion.id})
        cls.sin_fsm = Employee.create({'name': 'sin fsm'})
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
        """Con definición pero sin instancia todavía: no tiene FSM activo, y la
        búsqueda negativa tiene que encontrarlo igual."""
        pendiente = self.env['hr.employee'].create(
            {'name': 'con definición, sin instancia', 'definition_id': self.definicion.id})
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
        """El empleado ya no es la instancia. Son dos registros con id propio, y
        el empleado sigue existiendo si la instancia se borra."""
        instancia = self.activo.fsm_instance_id
        self.assertTrue(instancia)
        self.assertEqual(instancia._name, 'fsm.instance')
        self.assertEqual(instancia.definition_id, self.definicion)
        instancia.unlink()
        self.assertTrue(self.activo.exists())
        self.assertFalse(self.activo.fsm_instance_id)

    def test_06_ensure_creates_the_instance_once(self):
        empleado = self.env['hr.employee'].create(
            {'name': 'una sola vez', 'definition_id': self.definicion.id})
        primera = empleado._ensure_fsm_instance()
        self.assertEqual(empleado._ensure_fsm_instance(), primera)

    def test_07_ensure_without_definition_says_so(self):
        with self.assertRaises(UserError):
            self.sin_fsm._ensure_fsm_instance()

    def test_08_related_fields_read_through_the_link(self):
        """Las vistas siguen pidiendo los mismos nombres al empleado."""
        instancia = self.pausado.fsm_instance_id
        instancia.write({'current_state_id': 'n_espera', 'next_node_id': 'n_otro'})
        self.assertEqual(self.pausado.fsm_state, 'paused')
        self.assertEqual(self.pausado.current_state_id, 'n_espera')
        self.assertEqual(self.pausado.next_node_id, 'n_otro')
        # ``debug_mode`` es el único que se escribe desde el empleado.
        self.pausado.debug_mode = 'step_by_step'
        self.assertEqual(instancia.debug_mode, 'step_by_step')

    def test_09_assigning_a_production_bot_starts_the_workflow(self):
        bot = self.env['hr.bot'].create({'name': 'Bot productivo'})
        # El bot es una fsm.definition por numa_poly; el diagrama se escribe en
        # la base, que es donde el compilador se dispara.
        definicion = bot.fsm_definition_id
        definicion.write({'json_ui_schema': _esquema_minimo(), 'state': 'production'})
        empleado = self.env['hr.employee'].create({'name': 'con bot'})
        self.assertFalse(empleado.fsm_instance_id)

        empleado.bot_id = bot

        self.assertEqual(empleado.definition_id, definicion)
        self.assertTrue(empleado.fsm_instance_id)
        self.assertEqual(empleado.fsm_state, 'running')
        self.assertEqual(empleado.current_state_id, 'n_espera')
        self.assertEqual(empleado.json_ui_schema, definicion.json_ui_schema)

    def test_10_start_action_refuses_twice(self):
        definicion = self.env['fsm.definition'].create({
            'name': 'Bot manual', 'json_ui_schema': _esquema_minimo()})
        empleado = self.env['hr.employee'].create(
            {'name': 'arranque manual', 'definition_id': definicion.id})
        empleado.action_start_fsm()
        self.assertEqual(empleado.fsm_state, 'running')
        with self.assertRaises(UserError):
            empleado.action_start_fsm()

    def test_11_the_bot_menu_action_opens(self):
        """``view_mode`` decía ``tree``, que dejó de ser un tipo de vista en 17.0.

        Nada lo valida al instalar —``ir.actions.act_window`` no controla el
        contenido de ``view_mode``—, así que la acción se instalaba entera y
        fallaba recién al abrir el menú."""
        accion = self.env.ref('numa_fsm_hr.action_hr_bot')
        modos = accion.view_mode.split(',')
        self.assertNotIn('tree', modos)
        self.env['hr.bot'].get_views([(False, modo) for modo in modos])
