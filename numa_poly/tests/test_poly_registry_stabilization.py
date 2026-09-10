# -*- coding: utf-8 -*-
"""
Lo que numa_poly hace cuando el registry termina de cargar.

Dos mecanismos colgaban de puntos que, en un arranque normal, no llegan a ejecutarse o pierden
lo que juntaron:

- El conjunto de vistas pendientes de validar era un ``lazy_property`` del registry.
  ``Registry.setup_models`` llama a ``lazy_property.reset_all()``, y durante un ``-u`` hay un
  ``setup_models`` por módulo actualizado: lo anotado al cargar un módulo se perdía al empezar
  el siguiente. En una actualización de 36 módulos llegaba al final 1 vista de cientos.

- La estabilización posterior a la carga la hacía un wrapper de ``Registry.new``. numa_poly se
  importa dentro de ``Registry.new``, así que en el primer arranque de cada proceso el wrapper no
  aplicaba y la estabilización no corría nunca. Cuando corría, en recargas, lo hacía fuera del
  lock y dejaba ``registry_invalidated`` en True, lo que hacía recargar a los demás workers.
  Ahora cuelga de ``Registry.signal_changes``, que ``Registry.new`` llama al final, bajo el lock.
"""
from unittest.mock import MagicMock, patch

from odoo.tests import tagged, TransactionCase
from odoo.tools import lazy_property

from ..models import poly as P


@tagged('post_install', '-at_install')
class TestPolyPendingViewsSurviveSetup(TransactionCase):

    def test_01_the_pending_set_is_not_a_lazy_property(self):
        """``reset_all`` borra solo los lazy_property: el conjunto no puede serlo."""
        self.assertNotIsInstance(type(self.registry).__dict__.get('_pending_poly_views'), lazy_property)

    def test_02_recorded_views_survive_a_registry_setup_reset(self):
        pendientes = self.registry._pending_poly_views
        centinela = -424242
        pendientes.add(centinela)
        try:
            lazy_property.reset_all(self.registry)   # lo que hace setup_models en cada módulo
            self.assertIn(centinela, self.registry._pending_poly_views,
                          "lo anotado se perdió con el reset de setup_models")
        finally:
            self.registry._pending_poly_views.discard(centinela)


@tagged('post_install', '-at_install')
class TestPolyRegistryStabilization(TransactionCase):

    def _registro(self, init):
        registro = type('Registro', (), {})()
        registro._init = init
        return registro

    def test_01_runs_once_per_registry_when_loading_is_over(self):
        registro = self._registro(init=False)
        with patch.object(P, '_poly_stabilize_registry') as estabilizar, \
                patch.object(P, '_original_registry_signal_changes') as original:
            P._poly_signal_changes(registro)
            P._poly_signal_changes(registro)
        estabilizar.assert_called_once_with(registro)
        self.assertEqual(original.call_count, 2, "la señal original tiene que salir siempre")

    def test_02_does_not_run_while_the_registry_is_loading(self):
        registro = self._registro(init=True)
        with patch.object(P, '_poly_stabilize_registry') as estabilizar, \
                patch.object(P, '_original_registry_signal_changes'):
            P._poly_signal_changes(registro)
        estabilizar.assert_not_called()

    def test_03_stabilizing_does_not_tell_other_workers_to_reload(self):
        """Re-armar los modelos pone registry_invalidated en True; no cambió nada que los otros
        procesos deban recargar, así que se restaura el valor que había."""
        registro = MagicMock()
        registro.registry_invalidated = False

        def setup(cr):
            registro.registry_invalidated = True
        registro.setup_models.side_effect = setup
        with patch.object(P, '_logger'):
            P._poly_stabilize_registry(registro)
        registro.setup_models.assert_called_once()
        registro._poly_finalize_view_validation.assert_called_once()
        self.assertFalse(registro.registry_invalidated)
        self.assertTrue(registro.ready)

    def test_04_the_registry_new_wrapper_is_gone(self):
        import odoo.modules.registry as registry_module
        self.assertFalse(hasattr(P, '_poly_registry_new'))
        self.assertIs(registry_module.Registry.signal_changes, P._poly_signal_changes)
