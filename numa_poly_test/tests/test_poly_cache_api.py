# -*- coding: utf-8 -*-
"""
How numa_poly touches the ORM cache.

Up to 18.0 it went through ``env.cache``. In 20.0 that accessor was deprecated
(``environments.py:655``: *"use fields method directly for cache
manipulation"*) and the manipulation moved to the field's methods. It is not
only style: ``Cache.insert_missing``, which poly used, **no longer exists**, so
that line would have raised ``AttributeError`` the day it ran.

The first test pins down that the new methods keep the names poly calls them
by. It is the lesson of ``_patch_ir_ui_view``: when Odoo renamed ``View`` to
``IrUiView``, a ``hasattr`` let it through in silence and the functionality
switched off without anything failing. A rename here has to produce a red test
with a name, not an ``AttributeError`` at the bottom of a ``create``.

The second one reads the source, and covers ``self._context`` along the way
(deprecated in 19.0 in favour of ``self.env.context``). It sounds crude, and it
is deliberate: the ``DeprecationWarning`` is no guard. ``Environment.cache`` is
a ``cached_property`` —it warns once per environment and no more— and the
``stacklevel`` attributes it to ``environments.py``, not to the file that
called it. A test listening for warnings would pass green with the old accessor
in place. Reading the source, by contrast, always fails and names the line.
"""
import inspect
import re

from odoo.orm.fields import Field
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.numa_poly.models import poly as P

# ORM accessors that Odoo deprecated and that numa_poly used.
DEPRECADOS = (
    (re.compile(r'\benv\.cache\s*\.'),
     'env.cache (20.0): use the field methods '
     '(_insert_cache / _invalidate_cache / _update_cache)'),
    (re.compile(r'\bself\._context\b'),
     'self._context (19.0): use self.env.context'),
)


@tagged('post_install', '-at_install')
class TestPolyCacheApi(TransactionCase):

    def test_01_the_field_cache_api_is_where_poly_expects_it(self):
        """The three methods that replaced ``env.cache`` in poly."""
        for nombre in ('_insert_cache', '_invalidate_cache', '_update_cache'):
            self.assertTrue(
                callable(getattr(Field, nombre, None)),
                "Field.%s does not exist: numa_poly calls it to manipulate the cache, "
                "and without it a polymorphic create fails with AttributeError" % nombre)

    def test_02_poly_does_not_use_deprecated_orm_accessors(self):
        fuente = inspect.getsource(P).splitlines()
        culpables = []
        for n, linea in enumerate(fuente, start=1):
            if linea.lstrip().startswith('#'):
                continue
            for patron, remedio in DEPRECADOS:
                if patron.search(linea):
                    culpables.append("  poly.py:%s  %s\n      -> %s" % (n, linea.strip(), remedio))
        self.assertFalse(culpables, "deprecated accessors in poly.py:\n" + "\n".join(culpables))

    def test_03_a_poly_create_leaves_the_base_fields_readable(self):
        """What the invalidation protects.

        ``create`` writes the base's fields through the manipulated
        descriptors, flushes and invalidates the cache before restoring them.
        If the invalidation does not happen, what stays in the cache is what
        the temporary path wrote, not what is in the base.
        """
        registro = self.env['test.poly.child.a'].create({
            'base_field': 'desde la base',
            'child_a_field': 'desde el concreto',
        })
        self.assertEqual(registro.base_field, 'desde la base')
        self.assertEqual(registro.child_a_field, 'desde el concreto')

        self.env.invalidate_all()
        self.assertEqual(registro.base_field, 'desde la base',
                         "the value never reached the base: the cache masked the write")
