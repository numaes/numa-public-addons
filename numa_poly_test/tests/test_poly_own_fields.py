# -*- coding: utf-8 -*-
"""
Qué campos redirige numa_poly hacia la fila de la base.

La contribución declara ``_inherit = [modelo] + bases``, así que todo lo que la
base hereda de un mixin le llega al concreto por ese mismo camino. Lo único que
hay que redirigir con un ``related`` es lo que es **dato de la base**.

Hasta 20.0 el filtro no existía y el conjunto se leía del MRO de
``registry[base]``. Eso hacía que dependiera del orden de armado: en un arranque
limpio la clase está cruda y ``fsm.definition`` daba 14 campos; en una
reconstrucción posterior ya trae ``mail.thread`` y ``mail.activity.mixin`` en el
MRO y daba 42. El mismo código y la misma base producían un modelo polimórfico
distinto según cuándo corriera: en la variante gorda ``message_ids`` pasaba a
leerse de la fila de la base en vez de la propia, y 17 campos calculados
quedaban declarados ``compute`` y ``related`` a la vez —Odoo avisaba y
descartaba el compute—.

El guarda es ``test_01``: corre con el registry ya armado, que es justamente la
condición en la que el defecto aparecía, y falla si el filtro se saca. Los otros
miran la contribución tal como quedó construida, y eso depende del orden de
armado —o sea, de lo mismo que este cambio corrige—, así que valen como
descripción de la forma esperada, no como red de seguridad.
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
        self.fail("%s no tiene contribución polimórfica" % modelo)

    def test_01_the_base_fields_are_the_bases_own(self):
        """Con el registry armado, el mixin no puede colarse."""
        campos = P._poly_base_field_names(self.env.registry, BASE)
        self.assertIn('dato_de_la_base', campos)
        self.assertNotIn('mixin_field', campos,
                         "mixin_field es del mixin, no de la base: el concreto ya lo "
                         "recibe por _inherit")
        self.assertNotIn('mixin_computed', campos)

    def test_02_the_contribution_only_redirects_the_bases_own_data(self):
        """La contribución tal como quedó construida, con el camino del related."""
        contribuidos = self._contribucion(CONCRETO)
        self.assertIn('dato_de_la_base', contribuidos)
        self.assertEqual(contribuidos['dato_de_la_base']._args__.get('related'),
                         'mixed_base_id.dato_de_la_base')
        for heredado in ('mixin_field', 'mixin_computed'):
            self.assertNotIn(heredado, contribuidos)

    def test_03_no_redirected_field_collides_with_a_computed_declaration(self):
        """La combinación que Odoo rechaza: avisa y descarta el compute
        (``fields.py:477``). Cuando pasaba, el campo dejaba de calcularse sin que
        nadie lo hubiera pedido.

        Se mira lo **declarado**, no el campo ya armado: a un related montado
        Odoo le pone ``compute='_compute_related'``, así que preguntarle al campo
        final da que todos los related son computados y no prueba nada.
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
                        culpables.append('%s.%s (compute declarado en %s)'
                                         % (nombre, campo.name, klass.__name__))
        self.assertFalse(
            culpables,
            "numa_poly redirige con related campos que otra clase de la cadena declara "
            "calculados; Odoo descarta el compute:\n  " + "\n  ".join(culpables))

    def test_04_the_inherited_field_still_works_on_the_concrete(self):
        """Lo que el filtro NO debe romper: el campo del mixin sigue llegando."""
        registro = self.env[CONCRETO].create({
            'dato_de_la_base': 'de la base',
            'dato_del_concreto': 'del concreto',
            'mixin_field': 'del mixin',
        })
        self.assertEqual(registro.mixin_computed, 'calculado por el mixin')
        self.assertEqual(registro.mixin_field, 'del mixin')
        self.assertEqual(registro.dato_del_concreto, 'del concreto')

        # El dato de la base sí vive en la fila de la base.
        self.assertEqual(registro.dato_de_la_base, 'de la base')
        self.assertEqual(registro.mixed_base_id.dato_de_la_base, 'de la base')
        self.env.invalidate_all()
        self.assertEqual(registro.dato_de_la_base, 'de la base')
