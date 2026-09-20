# -*- coding: utf-8 -*-
"""
The filters of the instance search target the live ``fsm_state`` field.

c15d075 renamed ``fsm.instance.state`` to ``fsm_state`` and the search view kept filtering and
grouping by ``state``. The view became invalid, and since the deferred validation of numa_poly did
not validate it, nobody noticed. The filters are checked by running their domains, not by reading
the XML.
"""
import ast

from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFSMInstanceSearchFilters(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        definicion = cls.env['fsm.definition'].create({'name': 'Filtros de instancias'})
        Instance = cls.env['fsm.instance']
        cls.corriendo = Instance.create({'name': 'filtro corriendo', 'definition_id': definicion.id})
        cls.pausada = Instance.create({'name': 'filtro pausada', 'definition_id': definicion.id})
        cls.sin_iniciar = Instance.create({'name': 'filtro sin iniciar', 'definition_id': definicion.id})
        cls.corriendo.fsm_state = 'running'
        cls.pausada.fsm_state = 'paused'
        cls.todas = cls.corriendo | cls.pausada | cls.sin_iniciar

    def _filtros(self):
        vista = self.env.ref('numa_fsm.instance_search_view')
        vista._check_xml()
        arch = self.env['fsm.instance'].get_view(vista.id, 'search')['arch']
        return {nodo.get('name'): nodo for nodo in etree.fromstring(arch).iter('filter')}

    def test_01_running_and_paused_filters_find_their_instances(self):
        filtros = self._filtros()
        for nombre, esperada in (('running', self.corriendo), ('paused', self.pausada)):
            dominio = ast.literal_eval(filtros[nombre].get('domain'))
            encontradas = self.env['fsm.instance'].search(dominio + [('id', 'in', self.todas.ids)])
            self.assertEqual(encontradas, esperada, nombre)

    def test_02_group_by_state_uses_an_existing_field(self):
        contexto = ast.literal_eval(self._filtros()['group_state'].get('context'))
        self.assertIn(contexto['group_by'], self.env['fsm.instance']._fields)
