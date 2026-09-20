# -*- coding: utf-8 -*-
"""
Cómo numa_poly toca la caché del ORM.

Hasta 18.0 se hacía por ``env.cache``. En 20.0 ese accesor quedó deprecado
(``environments.py:655``: *"use fields method directly for cache
manipulation"*) y la manipulación pasó a los métodos del campo. No es sólo
estilo: ``Cache.insert_missing``, que poly usaba, **ya no existe**, así que esa
línea habría levantado ``AttributeError`` el día que se ejecutara.

El primer test fija que los métodos nuevos sigan llamándose como poly los
llama. Es la lección de ``_patch_ir_ui_view``: cuando Odoo renombró ``View`` a
``IrUiView``, un ``hasattr`` lo dejó pasar en silencio y la funcionalidad se
apagó sin que nada fallara. Un rename acá tiene que dar un test rojo con
nombre, no un ``AttributeError`` en el fondo de un ``create``.

El segundo mira el fuente, y cubre de paso ``self._context`` (deprecado en
19.0 a favor de ``self.env.context``). Suena burdo, y es deliberado: el
``DeprecationWarning`` no sirve de guarda. ``Environment.cache`` es un
``cached_property`` —avisa una vez por entorno y no más— y el ``stacklevel`` lo
atribuye a ``environments.py``, no al archivo que lo llamó. Un test que
escuchara warnings pasaría en verde con el accesor viejo puesto. Leer el
fuente, en cambio, falla siempre y nombra la línea.
"""
import inspect
import re

from odoo.orm.fields import Field
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.numa_poly.models import poly as P

# Accesores del ORM que Odoo dejó deprecados y que numa_poly usaba.
DEPRECADOS = (
    (re.compile(r'\benv\.cache\s*\.'),
     'env.cache (20.0): usar los métodos del campo '
     '(_insert_cache / _invalidate_cache / _update_cache)'),
    (re.compile(r'\bself\._context\b'),
     'self._context (19.0): usar self.env.context'),
)


@tagged('post_install', '-at_install')
class TestPolyCacheApi(TransactionCase):

    def test_01_the_field_cache_api_is_where_poly_expects_it(self):
        """Los tres métodos que reemplazaron a ``env.cache`` en poly."""
        for nombre in ('_insert_cache', '_invalidate_cache', '_update_cache'):
            self.assertTrue(
                callable(getattr(Field, nombre, None)),
                "Field.%s no existe: numa_poly lo llama para manipular la caché, "
                "y sin él un create polimórfico falla con AttributeError" % nombre)

    def test_02_poly_does_not_use_deprecated_orm_accessors(self):
        fuente = inspect.getsource(P).splitlines()
        culpables = []
        for n, linea in enumerate(fuente, start=1):
            if linea.lstrip().startswith('#'):
                continue
            for patron, remedio in DEPRECADOS:
                if patron.search(linea):
                    culpables.append("  poly.py:%s  %s\n      -> %s" % (n, linea.strip(), remedio))
        self.assertFalse(culpables, "accesores deprecados en poly.py:\n" + "\n".join(culpables))

    def test_03_a_poly_create_leaves_the_base_fields_readable(self):
        """Lo que la invalidación protege.

        ``create`` escribe los campos de la base con los descriptores
        manipulados, hace flush e invalida la caché antes de restaurarlos. Si la
        invalidación no ocurre, lo que queda en caché es lo que escribió el
        camino temporal, no lo que hay en la base.
        """
        registro = self.env['test.poly.child.a'].create({
            'base_field': 'desde la base',
            'child_a_field': 'desde el concreto',
        })
        self.assertEqual(registro.base_field, 'desde la base')
        self.assertEqual(registro.child_a_field, 'desde el concreto')

        self.env.invalidate_all()
        self.assertEqual(registro.base_field, 'desde la base',
                         "el valor no llegó a la base: la caché tapaba la escritura")
