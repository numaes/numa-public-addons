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
  20.0 no existe. Se retiró entera, y no por falta de dónde colgarla: lo que hacía era repetir
  el setup para reinyectar el MRO, y eso dejó de hacer falta cuando la declaración reemplazó a
  la inyección. Odoo arma las bases solo, en la primera pasada, y no hay nada que rehacer.

  Lo único que quedaba pendiente para el final de la carga es validar las vistas diferidas, y
  eso tiene anclaje propio desde siempre: ``ir.poly_base._register_hook``, que Odoo llama con
  todos los módulos cargados (``registry.py:577``). Lo cubre ``test_poly_view_validation``.
"""
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestPolyPendingViews(TransactionCase):
    """Lo anotado durante la carga tiene que seguir ahí hasta que alguien lo valide."""

    def test_01_the_pending_set_is_the_same_object_across_reads(self):
        """Si cada lectura devolviera un conjunto nuevo, anotar no serviría de nada.

        Era un defecto real: como ``lazy_property`` guardaba el valor bajo el nombre de la
        función y no el del atributo, cada lectura creaba un conjunto vacío y la validación
        final no validaba nada.
        """
        self.assertIs(self.registry._pending_poly_views, self.registry._pending_poly_views)

    def test_02_what_is_recorded_stays_until_something_validates_it(self):
        """Anotar y leer no pierde nada.

        El invariante de 18.0 era más fuerte -sobrevivir a ``setup_models``- porque
        ``lazy_property.reset_all()`` vaciaba el conjunto una vez por módulo actualizado. En
        Odoo 20 no hay ``reset_all``, y lo que un ``_setup_models__`` sí hace es llamar a
        ``_register_hook`` (``registry.py:577``), que valida las pendientes y las descarta: eso
        es el anclaje funcionando, no una pérdida.
        """
        centinela = -424242
        self.registry._pending_poly_views.add(centinela)
        try:
            self.assertIn(centinela, self.registry._pending_poly_views)
        finally:
            self.registry._pending_poly_views.discard(centinela)


@tagged('post_install', '-at_install')
class TestPolyStabilizationIsGone(TransactionCase):
    """La estabilización se retiró: que no vuelva por la ventana."""

    def test_01_no_stabilization_machinery_is_left(self):
        from ..models import poly as P
        for nombre in ('_poly_stabilize_registry', '_poly_signal_changes', '_poly_registry_new'):
            self.assertFalse(hasattr(P, nombre),
                             "%s volvió: la declaración de bases hace innecesario "
                             "repetir el setup después de la carga" % nombre)

    def test_02_the_view_validation_anchor_is_the_register_hook(self):
        """El anclaje que sí sobrevivió a Odoo 20."""
        self.assertTrue(hasattr(self.registry, '_poly_finalize_view_validation'))
        self.assertTrue(hasattr(self.env['ir.poly_base'], '_register_hook'))
