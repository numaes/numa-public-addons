# -*- coding: utf-8 -*-
"""
Validación diferida de vistas.

Mientras se cargan módulos el MRO polimórfico puede estar incompleto, así que poly no valida las
vistas en el momento: las difiere al final de la carga. Había cuatro defectos encadenados: solo se
anotaban las vistas ``noupdate``, el conjunto de pendientes se perdía en cada lectura, y la
validación final colgaba de un wrapper de ``load_module_graph`` que no aplica a la carga en curso
(numa_poly se importa dentro de esa llamada), y ``Registry.setup_models`` borraba el conjunto al
empezar cada módulo. No se validaba nada. En una instalación real eso dejó 33 vistas rotas y activas
—incluidos errores de sintaxis que Odoo rechaza al cargar— sin que ningún ``-u`` avisara, en
módulos que usaban poly y en los que no.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools import config, mute_logger

from ..models import poly as P

LOGGER = 'odoo.addons.numa_poly.models.poly'
INVALIDA = '<form><field name="x_campo_que_no_existe"/></form>'
VALIDA = '<form><field name="name"/></form>'


@tagged('post_install', '-at_install')
class TestPolyDeferredViewValidation(TransactionCase):

    def setUp(self):
        super().setUp()
        previos = set(self.registry._pending_poly_views)

        def restaurar():
            self.registry._pending_poly_views.clear()
            self.registry._pending_poly_views.update(previos)
        self.addCleanup(restaurar)

    def _crear_durante_la_carga(self, arch, nombre):
        with patch.object(self.registry, '_init', True):
            return self.env['ir.ui.view'].create({
                'name': nombre, 'model': 'res.currency', 'type': 'form', 'arch': arch})

    def _finalizar(self, estricta):
        with patch.dict(config.options, {'poly_strict_view_validation': estricta}):
            self.registry._poly_finalize_view_validation(self.env.cr)

    def test_00_the_pending_set_survives_between_reads(self):
        """Cada lectura tiene que devolver el mismo conjunto. Cuando era un ``lazy_property`` guardado
        bajo el nombre de una función distinta del atributo, cada lectura creaba uno nuevo: todo lo
        anotado se perdía y la validación final no validaba nada. (Que además sobreviva al
        ``reset_all`` de ``setup_models`` lo cubre test_poly_registry_stabilization.)"""
        pendientes = self.registry._pending_poly_views
        self.assertIs(self.registry._pending_poly_views, pendientes)

    def test_01_during_loading_an_invalid_view_is_deferred_not_forgotten(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly diferida inválida')
        self.assertIn(vista.id, self.registry._pending_poly_views,
                      "la vista no quedó anotada: nunca se iba a validar")

    def test_02_strict_finalization_rejects_it_and_names_the_cause(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly diferida inválida')
        with mute_logger(LOGGER), self.assertRaises(ValidationError) as ctx:
            self._finalizar(True)
        self.assertIn('x_campo_que_no_existe', str(ctx.exception))
        self.assertNotIn(vista.id, self.registry._pending_poly_views)

    def test_03_lenient_finalization_reports_without_aborting(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly diferida inválida')
        with self.assertLogs(LOGGER, level='ERROR') as logs:
            self._finalizar(False)
        self.assertTrue(any('x_campo_que_no_existe' in line for line in logs.output), logs.output)
        self.assertNotIn(vista.id, self.registry._pending_poly_views)

    def test_04_a_valid_deferred_view_passes_silently(self):
        vista = self._crear_durante_la_carga(VALIDA, 'poly diferida válida')
        self.assertIn(vista.id, self.registry._pending_poly_views)
        self._finalizar(True)
        self.assertNotIn(vista.id, self.registry._pending_poly_views)

    def test_05_a_view_deleted_before_the_end_is_skipped(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly diferida borrada')
        vista.unlink()
        self._finalizar(True)

    def test_06_outside_loading_nothing_is_deferred(self):
        with self.assertRaises(ValidationError):
            self.env['ir.ui.view'].create({
                'name': 'poly inmediata', 'model': 'res.currency', 'type': 'form', 'arch': INVALIDA})

    def test_08_the_registry_hook_triggers_the_final_validation(self):
        """El disparador real: Odoo llama a ``_register_hook`` con todos los módulos cargados. El
        wrapper de ``load_module_graph`` no sirve en un arranque, porque poly se importa dentro de
        esa misma llamada."""
        self._crear_durante_la_carga(INVALIDA, 'poly diferida desde el hook')
        with patch.dict(config.options, {'poly_strict_view_validation': True}), \
                mute_logger(LOGGER), self.assertRaises(ValidationError) as ctx:
            self.env['ir.poly_base']._register_hook()
        self.assertIn('x_campo_que_no_existe', str(ctx.exception))

    def test_07_strictness_follows_the_option_then_the_test_mode(self):
        with patch.dict(config.options, {'poly_strict_view_validation': None, 'test_enable': True}):
            self.assertTrue(P._poly_strict_view_validation())
        with patch.dict(config.options, {'poly_strict_view_validation': None, 'test_enable': False}):
            self.assertFalse(P._poly_strict_view_validation())
        for valor, esperado in (('True', True), ('1', True), ('yes', True), ('false', False),
                                ('0', False), (True, True), (False, False)):
            with patch.dict(config.options, {'poly_strict_view_validation': valor, 'test_enable': False}):
                self.assertEqual(P._poly_strict_view_validation(), esperado, valor)
