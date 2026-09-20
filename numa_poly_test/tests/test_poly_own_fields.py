# -*- coding: utf-8 -*-
"""
Which fields numa_poly redirects to the base's row.

The contribution declares ``_inherit = [model] + bases``, so everything the base
inherits from a mixin reaches the concrete model through that same path. The only
thing that has to be redirected with a ``related`` is what is **base data**.

Up to 20.0 the filter did not exist and the set was read from the MRO of
``registry[base]``. That made it depend on the build order: on a clean boot the
class is bare and ``fsm.definition`` gave 14 fields; on a later rebuild it already
carries ``mail.thread`` and ``mail.activity.mixin`` in the MRO and gave 42. The
same code and the same base produced a different polymorphic model depending on
when it ran: in the fat variant ``message_ids`` started being read from the base's
row instead of its own, and 17 computed fields ended up declared ``compute`` and
``related`` at once —Odoo warned and dropped the compute—.

The guard is ``test_01``: it runs with the registry already built, which is exactly
the condition under which the defect appeared, and it fails if the filter is taken
out. The others look at the contribution as it was built, and that depends on the
build order —that is, on the very thing this change fixes—, so they are worth a
description of the expected shape, not a safety net.
"""
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.numa_poly.models import poly as P

BASE = 'test.poly.mixed.base'
CONCRETO = 'test.poly.mixed.child'


@tagged('post_install', '-at_install')
class TestPolyOwnFields(TransactionCase):

    def _contribucion(self, modelo):
        for klass in self.env.registry[modelo].mro():
            if klass.__name__.startswith('PolyContribution'):
                return {f.name: f for f in getattr(klass, '_field_definitions', ())}
        self.fail("%s has no polymorphic contribution" % modelo)

    def test_01_the_base_fields_are_the_bases_own(self):
        """With the registry built, the mixin cannot slip in."""
        campos = P._poly_base_field_names(self.env.registry, BASE)
        self.assertIn('dato_de_la_base', campos)
        self.assertNotIn('mixin_field', campos,
                         "mixin_field belongs to the mixin, not to the base: the "
                         "concrete already receives it through _inherit")
        self.assertNotIn('mixin_computed', campos)

    def test_02_the_contribution_only_redirects_the_bases_own_data(self):
        """The contribution as it was built, with the related's path."""
        contribuidos = self._contribucion(CONCRETO)
        self.assertIn('dato_de_la_base', contribuidos)
        self.assertEqual(contribuidos['dato_de_la_base']._args__.get('related'),
                         'mixed_base_id.dato_de_la_base')
        for heredado in ('mixin_field', 'mixin_computed'):
            self.assertNotIn(heredado, contribuidos)

    def test_03_no_redirected_field_collides_with_a_computed_declaration(self):
        """The combination Odoo rejects: it warns and drops the compute
        (``fields.py:477``). When it happened, the field stopped being computed
        without anyone having asked for it.

        What is inspected is the **declaration**, not the already built field: on
        an assembled related Odoo sets ``compute='_compute_related'``, so asking
        the final field says every related is computed and proves nothing.
        """
        culpables = []
        for nombre, modelo in self.env.registry.items():
            if not getattr(modelo, '_depend_models', None):
                continue
            contribucion = next(
                (k for k in modelo.mro() if k.__name__.startswith('PolyContribution')), None)
            if contribucion is None:
                continue
            redirigidos = {
                f.name for f in getattr(contribucion, '_field_definitions', ())
                if (getattr(f, '_args__', None) or {}).get('related')
            }
            for klass in modelo.mro():
                if klass is contribucion or getattr(klass, 'pool', None) is not None:
                    continue
                for campo in getattr(klass, '_field_definitions', ()):
                    if campo.name in redirigidos and (getattr(campo, '_args__', None) or {}).get('compute'):
                        culpables.append('%s.%s (compute declared in %s)'
                                         % (nombre, campo.name, klass.__name__))
        self.assertFalse(
            culpables,
            "numa_poly redirects with related fields that another class in the chain "
            "declares computed; Odoo drops the compute:\n  " + "\n  ".join(culpables))

    def test_04_the_inherited_field_still_works_on_the_concrete(self):
        """What the filter must NOT break: the mixin's field still arrives."""
        registro = self.env[CONCRETO].create({
            'dato_de_la_base': 'de la base',
            'dato_del_concreto': 'del concreto',
            'mixin_field': 'del mixin',
        })
        self.assertEqual(registro.mixin_computed, 'computed by the mixin')
        self.assertEqual(registro.mixin_field, 'del mixin')
        self.assertEqual(registro.dato_del_concreto, 'del concreto')

        # The base's data does live in the base's row.
        self.assertEqual(registro.dato_de_la_base, 'de la base')
        self.assertEqual(registro.mixed_base_id.dato_de_la_base, 'de la base')
        self.env.invalidate_all()
        self.assertEqual(registro.dato_de_la_base, 'de la base')
