# -*- coding: utf-8 -*-
"""Three defects found while porting numa_poly to Odoo 20, verified here on 18.0.

None of the three is a version breakage: the 20.0 port was simply the first time
anybody installed these modules on a clean database and ran the suites, and each
of the three turned out to be present in 18.0 as well.

See BACKPORT-18.0.md on the 20.0 branch, items 9, 10 and 11.
"""
from odoo.addons.numa_poly.models.poly import POLY_PROPAGATED
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestUnaClaveDesconocidaEsUnError(TransactionCase):
    """A key that is a field of nothing is an error, not something to drop.

    The polymorphic create distributes the values between this model, its bases and
    the link fields, and each branch is written as ``if k in <some>._fields``. A key
    matching none of them fell through all of them: the record was created without it
    and nothing was logged. Odoo raises ValueError for an unknown field, but that
    check lives in ``BaseModel.create``, which the polymorphic branch never calls.
    """

    def test_01_un_create_con_campo_inexistente_falla(self):
        with self.assertRaises(ValueError):
            self.env['test.poly.child.a'].create({
                'child_a_field': 'x',
                'no_existe_este_campo': 'y',
            })

    def test_02_un_campo_propio_sigue_siendo_valido(self):
        registro = self.env['test.poly.child.a'].create({'child_a_field': 'propio'})
        self.assertEqual(registro.child_a_field, 'propio')

    def test_03_un_campo_de_la_base_sigue_siendo_valido(self):
        """The guard must accept what the bases define, or it breaks every poly create."""
        registro = self.env['test.poly.child.a'].create({
            'child_a_field': 'propio',
            'base_field': 'de la base',
        })
        self.assertEqual(registro.base_field, 'de la base')

    def test_04_lo_propagado_por_poly_se_sigue_filtrando(self):
        """Values poly propagates from another model are filtered on purpose."""
        registro = self.env['test.poly.child.a'].with_context(
            **{POLY_PROPAGATED: True}
        ).create({'child_a_field': 'propagado', 'no_existe_este_campo': 'y'})
        self.assertTrue(registro.exists())


@tagged('post_install', '-at_install')
class TestUnRelatedInyectadoNoLlevaDefault(TransactionCase):
    """A default belongs to the model that STORES the field.

    numa_poly injects the base's fields into the concrete model as non-stored related
    ones. Odoo MERGES the attributes of same-named fields along the MRO, so a field
    that says nothing about `default` inherits the base model's and comes out
    `related` AND defaulted. Odoo applies a default on create, and writing a related
    field writes THROUGH to its target, so creating a concrete record against an
    EXISTING base row overwrote a value that row already held.

    On the 20.0 port this meant every inbound Twilio message was stored as outgoing.
    """

    def test_01_el_related_inyectado_no_tiene_default(self):
        campo = self.env['test.poly.child.a']._fields['base_defaulted']
        self.assertTrue(campo.related, "this test is about an injected related field")
        self.assertFalse(campo.store)
        self.assertFalse(
            campo.default,
            "a non-stored related field must not carry the base field's default")

    def test_02_el_default_sigue_valiendo_donde_el_valor_vive(self):
        base = self.env['test.poly.base'].create({'base_field': 'b'})
        self.assertEqual(base.base_defaulted, 'de-la-base',
                         "the base model keeps its own default")

    def test_03_un_valor_explicito_de_la_base_sobrevive(self):
        base = self.env['test.poly.base'].create({
            'base_field': 'b', 'base_defaulted': 'puesto a mano'})
        self.assertEqual(base.base_defaulted, 'puesto a mano')

        self.env['test.poly.child.a'].create({
            'base_id': base.id, 'child_a_field': 'hijo'})
        base.invalidate_recordset()
        self.assertEqual(base.base_defaulted, 'puesto a mano',
                         "the child's default was written through to the base")

    def test_04_lo_que_el_hijo_pide_explicitamente_si_llega(self):
        """Removing the default does not remove the ability to write."""
        base = self.env['test.poly.base'].create({
            'base_field': 'b', 'base_defaulted': 'inicial'})
        hijo = self.env['test.poly.child.a'].create({
            'base_id': base.id, 'child_a_field': 'hijo'})
        hijo.base_defaulted = 'escrito por el hijo'
        base.invalidate_recordset()
        self.assertEqual(base.base_defaulted, 'escrito por el hijo',
                         "an explicit write through the related field must still land")


@tagged('post_install', '-at_install')
class TestNativoSignificaDeclarado(TransactionCase):
    """"Native" must mean "a module declared it here", not "the class carries it".

    `_poly_native_field_names` decides which fields poly must NOT replace with a
    related-to-base version. It scanned `cls.mro()`, which also contains the
    registry's aggregate class — and that class carries EVERY field of the model,
    including the ones poly itself injected. So "native" came to mean "any field at
    all".

    It is cached, and the cache is filled during registry setup, when the aggregate
    class is not yet populated — which is why the answer depends on WHEN it is asked
    rather than on what the model declares. That is the part this test pins: it
    clears the cache and asks again.
    """

    def setUp(self):
        super().setUp()
        self.Child = self.env['test.poly.child.a']

    def _nativos_recalculados(self):
        from odoo.addons.numa_poly.models.poly import _POLY_NATIVE_FNAMES
        cls = type(self.Child)
        _POLY_NATIVE_FNAMES.pop(cls._name, None)
        try:
            return set(cls._poly_native_field_names())
        finally:
            _POLY_NATIVE_FNAMES.pop(cls._name, None)

    def test_01_lo_que_el_modelo_declara_es_nativo(self):
        self.assertIn('child_a_field', self._nativos_recalculados())

    def test_02_un_campo_de_la_base_no_es_nativo_aunque_la_clase_lo_lleve(self):
        """The regression: recomputed after setup, the answer used to change."""
        nativos = self._nativos_recalculados()
        self.assertNotIn(
            'base_field', nativos,
            "a field the base declares is not this model's own, whatever the "
            "aggregate class happens to carry when the question is asked")
        self.assertNotIn('base_defaulted', nativos)

    def test_03_la_respuesta_no_depende_de_cuando_se_pregunta(self):
        primera = self._nativos_recalculados()
        segunda = self._nativos_recalculados()
        self.assertEqual(primera, segunda)
