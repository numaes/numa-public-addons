# -*- coding: utf-8 -*-
"""Una última pasada cuando ya está todo cargado.

Los dos mecanismos de este módulo tienen cada uno su ventana ciega:

- ``pre_init_hook`` ensancha lo que existe, y es el único momento en que el
  esquema es el que construyeron los demás módulos. Pero en la misma corrida se
  instalan después los ``auto_install`` -``web``, ``auth_totp`` y lo que
  arrastren-, y sus tablas todavía no existen cuando corre.
- El parche de ``create_model_table`` atiende las tablas nuevas, y se verificó
  que lo hace. Pero un modelo con ``_auto = False`` no pasa por ahí: escribe su
  propia DDL, y en el core esa DDL dice ``id serial`` (``res_users.py:1554``),
  que es ``int4``.

El cruce de las dos es real y se veía en una instalación limpia:
``auth_totp_device`` -que es ``_auto = False`` y se instala después- quedaba con
su ``id`` en 32 bits, y la compuerta reportaba el módulo ``installed`` igual. Un
módulo que dice ``installed`` sobre una base a medio ensanchar es exactamente lo
que este módulo existe para impedir.

``_register_hook`` es el anclaje que faltaba: Odoo lo llama con todos los
módulos cargados (``registry.py:577``), que es después de los ``auto_install`` y
después de cualquier ``init()`` a mano.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Marca en el registry: la barrida es una por generación, no una por modelo.
_SWEPT = '_big_id_swept__'


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def _register_hook(self):
        resultado = super()._register_hook()
        registry = self.env.registry
        if registry.__dict__.get(_SWEPT):
            return resultado
        setattr(registry, _SWEPT, True)

        from ..hooks import _pending_columns, migrate_to_bigint, log_verification

        cr = self.env.cr
        pendientes = _pending_columns(cr)
        if not pendientes:
            return resultado

        _logger.info("[big_id] %s tabla(s) quedaron en 32 bits tras cargar los módulos; "
                     "se ensanchan: %s", len(pendientes), ', '.join(sorted(pendientes)))
        migrate_to_bigint(cr)
        resultado_verificacion = log_verification(cr)
        if not resultado_verificacion['clean']:
            # No se aborta la carga: llegado este punto los módulos ya están
            # instalados y abortar deja la base peor. Se reporta con todo el
            # detalle, que es lo que log_verification acaba de escribir.
            _logger.error("[big_id] la base sigue teniendo columnas de 32 bits después de "
                          "la barrida final; el log de arriba las nombra")
        return resultado
