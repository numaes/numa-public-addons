# -*- coding: utf-8 -*-
"""
Lo que numa_poly hace cuando el registry termina de cargar.

En 18.0 dos mecanismos colgaban de puntos que, en un arranque normal, no llegaban a ejecutarse
o perdían lo que juntaban. Odoo 20.0 se llevó puestos los dos puntos de enganche, así que este
archivo quedó partido en dos mitades de distinto estado:

- **Las vistas pendientes de validar.** El conjunto era un ``lazy_property`` del registry, y
  ``setup_models`` llamaba a ``lazy_property.reset_all()`` una vez por módulo actualizado: lo
  anotado al cargar un módulo se perdía al empezar el siguiente. En 20.0 ``lazy_property`` no
  existe, el conjunto es un ``functools.cached_property``, y ``_setup_models__`` no resetea
  nada equivalente. El riesgo desapareció por construcción, y lo que sigue abajo lo verifica.

- **La estabilización posterior a la carga.** Colgaba de ``Registry.signal_changes``, que en
  20.0 no existe: ``_signal_changes(cr, names)`` es otro contrato (por transacción, desde
  ``environments.py:976``), ``Registry.new`` termina en ``registry.ready = True`` sin enganche,
  y ``registry._init`` / ``registry.registry_invalidated`` tampoco están. Elegir el anclaje
  nuevo es la fase 6 del rediseño. Hasta entonces no hay mecanismo que probar, y sus tests se
  saltean diciéndolo en voz alta en lugar de pasar por vacío.
"""
import unittest

from odoo.tests import tagged, TransactionCase

FASE_6 = ("pendiente de la fase 6 del rediseño: Registry.signal_changes no existe en Odoo 20.0 "
          "y todavía no se eligió el anclaje que lo reemplaza "
          "(ver doc/plan-2026-09-20-odoo-20-redesign.md, sección 2.4)")


@tagged('post_install', '-at_install')
class TestPolyPendingViewsSurviveSetup(TransactionCase):
    """Lo anotado durante la carga tiene que seguir ahí cuando la carga termina."""

    def test_01_the_pending_set_survives_a_models_setup(self):
        pendientes = self.registry._pending_poly_views
        centinela = -424242
        pendientes.add(centinela)
        try:
            self.registry._setup_models__(self.env.cr, [])   # setup incremental, como en un -u
            self.assertIn(centinela, self.registry._pending_poly_views,
                          "lo anotado se perdió al rearmar los modelos")
        finally:
            self.registry._pending_poly_views.discard(centinela)

    def test_02_the_pending_set_is_the_same_object_across_reads(self):
        """Si cada lectura devolviera un conjunto nuevo, anotar no serviría de nada."""
        self.assertIs(self.registry._pending_poly_views, self.registry._pending_poly_views)


@tagged('post_install', '-at_install')
@unittest.skip(FASE_6)
class TestPolyRegistryStabilization(TransactionCase):
    """La estabilización posterior a la carga, cuando vuelva a tener dónde colgarse."""

    def test_01_runs_once_per_registry_when_loading_is_over(self):
        self.fail(FASE_6)

    def test_02_does_not_run_while_the_registry_is_loading(self):
        self.fail(FASE_6)

    def test_03_stabilizing_does_not_tell_other_workers_to_reload(self):
        self.fail(FASE_6)
