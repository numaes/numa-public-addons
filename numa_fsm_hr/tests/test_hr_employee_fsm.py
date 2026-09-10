# -*- coding: utf-8 -*-
"""
hr.employee como instancia FSM: la búsqueda por ``has_fsm`` y las vistas.

El módulo no se podía instalar en 18.0. El form heredaba con un selector por ``string`` (Odoo lo
prohíbe desde la 17); la búsqueda heredaba de ``hr.view_employee_search``, que en 18 es
``hr.view_employee_filter``, y se anclaba en un filtro ``my_employees`` que no existe. Además,
``has_fsm`` era computado sin ``search`` y las vistas usaban ``state`` después del renombre a
``fsm_state`` en numa_fsm.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrEmployeeFsm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        definicion = cls.env['fsm.definition'].create({'name': 'Bot de empleados'})
        Employee = cls.env['hr.employee']
        cls.activo = Employee.create({'name': 'fsm activo', 'definition_id': definicion.id})
        cls.pausado = Employee.create({'name': 'fsm pausado', 'definition_id': definicion.id})
        cls.terminado = Employee.create({'name': 'fsm terminado', 'definition_id': definicion.id})
        cls.sin_fsm = Employee.create({'name': 'sin fsm'})
        cls.activo.fsm_state = 'running'
        cls.pausado.fsm_state = 'paused'
        cls.terminado.fsm_state = 'ended'
        cls.todos = cls.activo | cls.pausado | cls.terminado | cls.sin_fsm

    def _buscar(self, dominio):
        return self.env['hr.employee'].search(dominio + [('id', 'in', self.todos.ids)])

    def test_01_search_agrees_with_compute(self):
        con = self.todos.filtered('has_fsm')
        self.assertEqual(con, self.activo | self.pausado)
        sin = self.todos - con
        self.assertEqual(self._buscar([('has_fsm', '=', True)]), con)
        self.assertEqual(self._buscar([('has_fsm', '!=', False)]), con)
        self.assertEqual(self._buscar([('has_fsm', '=', False)]), sin)
        self.assertEqual(self._buscar([('has_fsm', '!=', True)]), sin)

    def test_02_views_validate(self):
        for xmlid in ('numa_fsm_hr.view_hr_employee_form_fsm', 'numa_fsm_hr.view_hr_employee_tree_fsm',
                      'numa_fsm_hr.view_hr_employee_search_fsm'):
            self.env.ref(xmlid)._check_xml()
