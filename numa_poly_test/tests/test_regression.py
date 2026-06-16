# -*- coding: utf-8 -*-
"""
Suite de regresión de numa_poly — red para validar antes de tocar producción.

Ancla con tests el comportamiento esperado en los cruces con el ORM de Odoo donde poly
parchea (herencia vs override, CRUD en diamante, campos heredados/sobrecargados,
concrete_model_id/as_concrete_model). Cada bug encontrado y arreglado (jun-2026) deja acá
su test para que no vuelva en silencio.

Jerarquías fixture:
  Diamante shared-PK:  test.test1 (a1,a2)
                         /            \\
                  test.test2 (a3)   test.test3 (a4)
                         \\            /
                       test.test4 (a3 sobrecargado, a4; override set_a1)
  Inyección de comportamientos: test.poly.project depende de behavior.a (field_a) + behavior.b (field_b).
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPolyMethodOverride(TransactionCase):
    """Herencia Y override de métodos a través de la jerarquía poly (fix MRO c377ea5)."""

    def test_concrete_override_wins(self):
        """El override del concreto gana sobre el método del padre (no al revés)."""
        t4 = self.env['test.test4'].create({'a1': 'x', 'a2': 'y', 'a3': 'z'})
        t4.set_a1()
        self.assertEqual(t4.a1, 'Set by test4',
                         "test.test4 debe correr SU override de set_a1, no el de Test1.")

    def test_base_method_on_base(self):
        """En el modelo base corre su propio método."""
        t1 = self.env['test.test1'].create({'a1': 'x'})
        t1.set_a1()
        self.assertEqual(t1.a1, 'Set by test1')

    def test_inherited_method_when_not_overridden(self):
        """Un concreto que NO overridea hereda el método del padre (test.test2 no override)."""
        t2 = self.env['test.test2'].create({'a3': 'z'})
        t2.set_a1()
        self.assertEqual(t2.a1, 'Set by test1',
                         "test.test2 no overridea set_a1 -> hereda el de Test1.")


@tagged('post_install', '-at_install')
class TestPolyDiamondCRUD(TransactionCase):
    """write / search / unlink en el diamante (test.test4). Guarda el bug de unlink (7ea316e)."""

    def test_write_inherited_field_persists(self):
        """Escribir un campo heredado (a1, de Test1) persiste y se lee consistente."""
        t4 = self.env['test.test4'].create({'a1': 'C1', 'a2': 'C2', 'a3': 'C3'})
        t4.a1 = 'D1'
        t4.flush_recordset()
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'D1')
        # El valor vive en el test1 compartido (mismo id).
        self.assertEqual(self.env['test.test1'].browse(t4.id).a1, 'D1')

    def test_search_inherited_field(self):
        """Buscar por un campo heredado encuentra el registro del diamante."""
        t4 = self.env['test.test4'].create({'a1': 'UNIQUE_A1', 'a2': 'b', 'a3': 'c'})
        found = self.env['test.test4'].search([('a1', '=', 'UNIQUE_A1')])
        self.assertEqual(found, t4)

    def test_search_own_field(self):
        """Buscar por un campo propio del concreto (a4)."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a4': 'OWN_A4'})
        found = self.env['test.test4'].search([('a4', '=', 'OWN_A4')])
        self.assertEqual(found, t4)

    def test_unlink_cascades_all_bases(self):
        """unlink borra el concreto Y todas las bases compartidas; nunca cuelga."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': 'b', 'a3': 'c', 'a4': 'd'})
        tid = t4.id
        self.assertTrue(self.env['test.test1'].browse(tid).exists())
        self.assertTrue(self.env['test.test2'].browse(tid).exists())
        self.assertTrue(self.env['test.test3'].browse(tid).exists())
        t4.unlink()
        self.assertFalse(self.env['test.test4'].browse(tid).exists())
        self.assertFalse(self.env['test.test1'].browse(tid).exists())
        self.assertFalse(self.env['test.test2'].browse(tid).exists())
        self.assertFalse(self.env['test.test3'].browse(tid).exists())
        self.assertFalse(self.env['ir.poly_base'].browse(tid).exists())

    def test_bulk_unlink(self):
        """unlink de varios registros del diamante a la vez."""
        recs = self.env['test.test4'].create([
            {'a1': 'u1', 'a3': 'p'}, {'a1': 'u2', 'a3': 'q'}, {'a1': 'u3', 'a3': 'r'}])
        ids = recs.ids
        recs.unlink()
        for tid in ids:
            self.assertFalse(self.env['test.test4'].browse(tid).exists())
            self.assertFalse(self.env['test.test1'].browse(tid).exists())

    def test_write_mixed_inherited_and_own_fields(self):
        """write que toca a la vez un campo heredado (a1, de Test1) y uno propio (a4)."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a4': 'x'})
        t4.write({'a1': 'a2', 'a4': 'y'})
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'a2')
        self.assertEqual(t4.a4, 'y')
        self.assertEqual(self.env['test.test1'].browse(t4.id).a1, 'a2',
                         "El campo heredado debe persistir en la base compartida.")

    def test_overloaded_field_shares_value(self):
        """a3 está declarado en Test2 y sobrecargado en Test4: comparten el valor (delegado al mismo id)."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a3': 'SHARED'})
        self.assertEqual(t4.a3, 'SHARED')
        self.assertEqual(self.env['test.test2'].browse(t4.id).a3, 'SHARED',
                         "El campo sobrecargado comparte valor con el del padre (mismo id).")

    def test_copy_creates_new_identity_with_copied_data(self):
        """copy() crea un nuevo id con su propio ir_poly_base y copia los datos (no los links poly)."""
        t4 = self.env['test.test4'].create({'a1': 'orig', 'a2': 'b', 'a3': 'c', 'a4': 'd'})
        dup = t4.copy()
        self.assertNotEqual(dup.id, t4.id, "La copia debe tener identidad propia.")
        # Datos copiados (incl. heredados de las bases):
        self.assertEqual(dup.a1, 'orig')
        self.assertEqual(dup.a2, 'b')
        self.assertEqual(dup.a4, 'd')
        # Identidad poly fresca y consistente:
        self.assertTrue(self.env['ir.poly_base'].browse(dup.id).exists(),
                        "La copia debe tener su propia entrada en ir_poly_base.")
        self.assertEqual(dup.concrete_model_id.model, 'test.test4')
        # Las bases de la copia son propias (mismo id que la copia, no las del original):
        self.assertEqual(self.env['test.test1'].browse(dup.id).a1, 'orig')
        self.assertTrue(self.env['test.test2'].browse(dup.id).exists())
        self.assertTrue(self.env['test.test3'].browse(dup.id).exists())
        # El original queda intacto:
        self.assertEqual(t4.a1, 'orig')

    def test_copy_with_default_override(self):
        """copy(default=...) aplica overrides sobre los datos copiados."""
        t4 = self.env['test.test4'].create({'a1': 'orig', 'a4': 'd'})
        dup = t4.copy({'a4': 'override'})
        self.assertEqual(dup.a1, 'orig', "Lo no overrideado se copia.")
        self.assertEqual(dup.a4, 'override', "El default override gana.")

    def test_mapped_filtered_sorted_on_inherited_field(self):
        """mapped()/filtered()/sorted() sobre un campo heredado en un recordset.
        Es el patrón exacto que loopeaba en unlink (mapped sobre PolyReference) — guardián."""
        recs = self.env['test.test4'].create([
            {'a1': 'm1', 'a2': 'M'}, {'a1': 'm2', 'a2': 'M'}, {'a1': 'm3', 'a2': 'M'}])
        self.assertEqual(sorted(recs.mapped('a1')), ['m1', 'm2', 'm3'])
        self.assertEqual(recs.filtered(lambda r: r.a1 == 'm2').a1, 'm2')
        self.assertEqual(recs.sorted('a1', reverse=True).mapped('a1'), ['m3', 'm2', 'm1'])

    def test_write_via_base_model_reflects_on_concrete(self):
        """Escribir el campo en el modelo BASE (mismo id) se ve desde el concreto."""
        t4 = self.env['test.test4'].create({'a1': 'orig'})
        self.env['test.test1'].browse(t4.id).a1 = 'from_base'
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'from_base')


@tagged('post_install', '-at_install')
class TestPolyConcreteModel(TransactionCase):
    """concrete_model_id / as_concrete_model y que el subtipo NO almacene el campo (fix a70da3b)."""

    def test_concrete_model_id_value(self):
        t4 = self.env['test.test4'].create({'a1': 'a'})
        self.assertEqual(t4.concrete_model_id.model, 'test.test4')

    def test_as_concrete_model_navigates(self):
        t4 = self.env['test.test4'].create({'a1': 'a'})
        base = self.env['ir.poly_base'].browse(t4.id)
        self.assertEqual(base.as_concrete_model()._name, 'test.test4')

    def test_concrete_model_id_not_stored_on_subtype(self):
        """concrete_model_id es de ir.poly_base: en el subtipo debe ser NO-stored (computado)."""
        field = self.env['test.test4']._fields['concrete_model_id']
        self.assertFalse(field.store,
                         "concrete_model_id no debe ser columna stored del subtipo.")


@tagged('post_install', '-at_install')
class TestPolyBehaviorInjection(TransactionCase):
    """Inyección de comportamientos (test.poly.project: 2 _depend_models). Guarda create/search/unlink."""

    def test_create_injects_both_behaviors(self):
        p = self.env['test.poly.project'].create({'name': 'P', 'field_a': 'A', 'field_b': 9})
        self.assertEqual(p.behavior_a_id.id, p.id)
        self.assertEqual(p.behavior_b_id.id, p.id)
        self.assertEqual(self.env['test.poly.behavior.a'].browse(p.id).field_a, 'A')
        self.assertEqual(self.env['test.poly.behavior.b'].browse(p.id).field_b, 9)

    def test_search_injected_field(self):
        self.env['test.poly.project'].create({'name': 'P1', 'field_a': 'FIND'})
        self.env['test.poly.project'].create({'name': 'P2', 'field_a': 'NOPE'})
        found = self.env['test.poly.project'].search([('field_a', '=', 'FIND')])
        self.assertEqual(len(found), 1)
        self.assertEqual(found.name, 'P1')

    def test_write_injected_field(self):
        p = self.env['test.poly.project'].create({'name': 'P', 'field_a': 'old', 'field_b': 1})
        p.write({'field_a': 'new', 'field_b': 2})
        self.assertEqual(self.env['test.poly.behavior.a'].browse(p.id).field_a, 'new')
        self.assertEqual(self.env['test.poly.behavior.b'].browse(p.id).field_b, 2)

    def test_unlink_injected_behaviors(self):
        p = self.env['test.poly.project'].create({'name': 'P', 'field_a': 'A', 'field_b': 1})
        pid = p.id
        p.unlink()
        self.assertFalse(self.env['test.poly.project'].browse(pid).exists())
        self.assertFalse(self.env['test.poly.behavior.a'].browse(pid).exists())
        self.assertFalse(self.env['test.poly.behavior.b'].browse(pid).exists())


@tagged('post_install', '-at_install')
class TestPolySearchReadAggregate(TransactionCase):
    """search (orden y operadores sobre campos heredados), read batch, display_name, read_group, m2o.
    Usa un marcador único en a2 para aislar los registros del test del resto de la tabla."""

    MARK = '__SRA__'  # marcador para aislar (campo a2, heredado de Test1)

    def _make(self, a1, a4=False):
        return self.env['test.test4'].create({'a1': a1, 'a2': self.MARK, 'a4': a4})

    def test_order_by_inherited_field(self):
        """search(order=) por un campo HEREDADO (a1, vive en test_test1) — ancla el patch
        _order_field_to_sql de expression.py (ordenar por columna ausente de la tabla hoja)."""
        self._make('B'); self._make('A'); self._make('C')
        recs_asc = self.env['test.test4'].search([('a2', '=', self.MARK)], order='a1 asc')
        self.assertEqual(recs_asc.mapped('a1'), ['A', 'B', 'C'])
        recs_desc = self.env['test.test4'].search([('a2', '=', self.MARK)], order='a1 desc')
        self.assertEqual(recs_desc.mapped('a1'), ['C', 'B', 'A'])

    def test_domain_operators_on_inherited_field(self):
        """Operadores in / not in / like / != sobre un campo heredado."""
        self._make('alpha'); self._make('beta'); self._make('gamma')
        base = [('a2', '=', self.MARK)]
        self.assertEqual(
            self.env['test.test4'].search(base + [('a1', 'in', ['alpha', 'gamma'])]).mapped('a1'),
            ['alpha', 'gamma'])
        self.assertEqual(
            self.env['test.test4'].search(base + [('a1', 'like', 'bet')]).mapped('a1'), ['beta'])
        self.assertEqual(
            sorted(self.env['test.test4'].search(base + [('a1', '!=', 'beta')]).mapped('a1')),
            ['alpha', 'gamma'])

    def test_domain_combines_inherited_and_own_fields(self):
        """Dominio que mezcla campo heredado (a1) y propio (a4) en el mismo search."""
        self._make('x', a4='keep')
        self._make('x', a4='drop')
        found = self.env['test.test4'].search(
            [('a2', '=', self.MARK), ('a1', '=', 'x'), ('a4', '=', 'keep')])
        self.assertEqual(len(found), 1)
        self.assertEqual(found.a4, 'keep')

    def test_search_count_with_inherited_domain(self):
        self._make('A'); self._make('A'); self._make('B')
        self.assertEqual(
            self.env['test.test4'].search_count([('a2', '=', self.MARK), ('a1', '=', 'A')]), 2)

    def test_read_batch_mixed_fields(self):
        """read() de varios campos (heredado a1/a2, sobrecargado a3, propio a4) en una llamada."""
        t4 = self.env['test.test4'].create({'a1': 'i', 'a2': 'ii', 'a3': 'iii', 'a4': 'iv'})
        data = t4.read(['a1', 'a2', 'a3', 'a4'])[0]
        self.assertEqual(data['a1'], 'i')
        self.assertEqual(data['a2'], 'ii')
        self.assertEqual(data['a3'], 'iii')
        self.assertEqual(data['a4'], 'iv')

    def test_display_name_is_singleton_string(self):
        """display_name no rompe sobre un registro poly (no hay _rec_name custom: forma por defecto)."""
        t4 = self.env['test.test4'].create({'a1': 'a'})
        self.assertIsInstance(t4.display_name, str)
        self.assertTrue(t4.display_name)

    def test_own_many2one_field(self):
        """Campo m2o propio del concreto (partner_id en Test4): set, lectura y búsqueda."""
        partner = self.env['res.partner'].create({'name': 'Poly Partner SRA'})
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': self.MARK, 'partner_id': partner.id})
        self.assertEqual(t4.partner_id, partner)
        found = self.env['test.test4'].search([('a2', '=', self.MARK), ('partner_id', '=', partner.id)])
        self.assertEqual(found, t4)

    def test_read_group_by_inherited_field(self):
        """read_group agrupando por un campo heredado (a1) cuenta correctamente."""
        self._make('G1'); self._make('G1'); self._make('G2')
        groups = self.env['test.test4'].read_group(
            [('a2', '=', self.MARK)], fields=['a1'], groupby=['a1'])
        counts = {g['a1']: g['a1_count'] for g in groups}
        self.assertEqual(counts.get('G1'), 2)
        self.assertEqual(counts.get('G2'), 1)


@tagged('post_install', '-at_install')
class TestPolyPolymorphicRecordset(TransactionCase):
    """El núcleo de poly: varios concretos comparten una base, y se navega de base a concreto.
    Usa la jerarquía test.poly.base <- {child.a, child.b} (dos concretos sobre la misma base)."""

    def test_as_concrete_model_resolves_mixed_types(self):
        """Distintos concretos sobre la misma base poly se resuelven cada uno a SU tipo."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'a', 'child_a_field': 'x'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'b', 'child_b_field': 'y'})
        base_a = self.env['ir.poly_base'].browse(ca.id)
        base_b = self.env['ir.poly_base'].browse(cb.id)
        self.assertEqual(base_a.as_concrete_model()._name, 'test.poly.child.a')
        self.assertEqual(base_b.as_concrete_model()._name, 'test.poly.child.b')
        self.assertNotEqual(ca.concrete_model_id, cb.concrete_model_id,
                            "Cada concreto tiene su propio concrete_model_id.")

    def test_shared_base_distinct_identities(self):
        """child.a y child.b comparten test.poly.base como base, pero tienen ids propios distintos."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'A', 'child_a_field': '1'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'B', 'child_b_field': '2'})
        self.assertNotEqual(ca.id, cb.id)
        self.assertEqual(self.env['test.poly.base'].browse(ca.id).base_field, 'A')
        self.assertEqual(self.env['test.poly.base'].browse(cb.id).base_field, 'B')

    def test_single_parent_full_crud(self):
        """CRUD completo en jerarquía de 1 nivel (child.a -> base): create/write/search/unlink."""
        c = self.env['test.poly.child.a'].create({'base_field': 'bf', 'child_a_field': 'cf'})
        cid = c.id
        # write de campo heredado (base_field) y propio (child_a_field) juntos
        c.write({'base_field': 'bf2', 'child_a_field': 'cf2'})
        c.invalidate_recordset()
        self.assertEqual(c.base_field, 'bf2')
        self.assertEqual(c.child_a_field, 'cf2')
        self.assertEqual(self.env['test.poly.base'].browse(cid).base_field, 'bf2',
                         "El heredado persiste en la base compartida.")
        # search por campo heredado
        found = self.env['test.poly.child.a'].search([('base_field', '=', 'bf2')])
        self.assertEqual(found, c)
        # unlink cascada a la base
        c.unlink()
        self.assertFalse(self.env['test.poly.child.a'].browse(cid).exists())
        self.assertFalse(self.env['test.poly.base'].browse(cid).exists())

    def test_as_concrete_model_over_mixed_list(self):
        """as_concrete_model iterando una lista MIXTA de ir.poly_base — base del rendering
        polimórfico de listas en la UI. Cada base se resuelve a su modelo concreto."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'a', 'child_a_field': 'x'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'b', 'child_b_field': 'y'})
        t4 = self.env['test.test4'].create({'a1': 'z'})
        bases = self.env['ir.poly_base'].browse([ca.id, cb.id, t4.id])
        names = [b.as_concrete_model()._name for b in bases]
        self.assertEqual(names, ['test.poly.child.a', 'test.poly.child.b', 'test.test4'])


@tagged('post_install', '-at_install')
class TestPolyLinksAndSearch(TransactionCase):
    """Links PolyReference (navegar concreto->base por el campo link), name_search y paginación."""

    def test_polyreference_link_navigation(self):
        """Los link fields (test2_id/test3_id) apuntan al registro base del MISMO id y dan sus datos."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': 'b', 'a3': 'c', 'a4': 'd'})
        self.assertEqual(t4.test2_id._name, 'test.test2')
        self.assertEqual(t4.test2_id.id, t4.id, "El link comparte id (shared-PK).")
        self.assertEqual(t4.test3_id.id, t4.id)
        # a3 está en test.test2: vía el link se ve el mismo valor.
        self.assertEqual(t4.test2_id.a3, t4.a3)

    def test_name_search_on_named_model(self):
        """name_search sobre un modelo poly con campo name (test.poly.project) filtra por name."""
        self.env['test.poly.project'].create({'name': 'Alpha NS', 'field_a': '1'})
        self.env['test.poly.project'].create({'name': 'Beta NS', 'field_a': '2'})
        res = self.env['test.poly.project'].name_search('Alpha')
        names = [n for _id, n in res]
        self.assertIn('Alpha NS', names)
        self.assertNotIn('Beta NS', names)

    def test_display_name_uses_own_name_not_base(self):
        """display_name de un modelo poly con campo name usa SU name, no el del primer base.
        Guarda el fix de des-delegación de _inherits sobre display_name (rendering de listas poly)."""
        p = self.env['test.poly.project'].create({'name': 'Proj X', 'field_a': '1'})
        self.assertEqual(p.display_name, 'Proj X',
                         "display_name debe ser el name propio, no 'test.poly.behavior.a,<id>'.")

    def test_search_pagination_on_inherited_field(self):
        """limit/offset con order por campo heredado devuelven el slice correcto."""
        mark = '__PAGIN__'
        for v in ['a', 'b', 'c', 'd', 'e']:
            self.env['test.test4'].create({'a1': v, 'a2': mark})
        page = self.env['test.test4'].search(
            [('a2', '=', mark)], order='a1 asc', limit=2, offset=1)
        self.assertEqual(page.mapped('a1'), ['b', 'c'])


@tagged('post_install', '-at_install')
class TestPolyDepthDefaultsM2o(TransactionCase):
    """Consulta a nivel base (abarca concretos), cadena de 3 niveles, dominio con punto por m2o,
    default_get, create mínimo, copy 1-nivel, y manejo de un m2o propio (set/clear/change)."""

    def test_base_model_search_spans_concretes(self):
        """search sobre el modelo BASE encuentra los registros de TODOS sus concretos.
        Es la consulta polimórfica de fondo (una lista de la base ve child.a y child.b)."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'SPAN', 'child_a_field': '1'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'SPAN', 'child_b_field': '2'})
        bases = self.env['test.poly.base'].search([('base_field', '=', 'SPAN')])
        self.assertEqual(set(bases.ids), {ca.id, cb.id},
                         "La base debe ver los registros de ambos concretos.")

    def test_write_via_intermediate_base_propagates(self):
        """Cadena de 3 niveles: escribir a1 en la base intermedia test.test2 (mismo id) se ve
        desde el concreto test.test4 Y desde la raíz test.test1."""
        t4 = self.env['test.test4'].create({'a1': 'orig'})
        self.env['test.test2'].browse(t4.id).a1 = 'via_t2'
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'via_t2')
        self.assertEqual(self.env['test.test1'].browse(t4.id).a1, 'via_t2')

    def test_dotted_domain_through_own_m2o(self):
        """Dominio con punto a través de un m2o propio: buscar test4 por partner_id.name."""
        partner = self.env['res.partner'].create({'name': 'Dotted Partner ZZ'})
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': '__DOT__', 'partner_id': partner.id})
        self.env['test.test4'].create({'a1': 'b', 'a2': '__DOT__'})
        found = self.env['test.test4'].search(
            [('a2', '=', '__DOT__'), ('partner_id.name', '=', 'Dotted Partner ZZ')])
        self.assertEqual(found, t4)

    def test_default_get_returns_dict(self):
        """default_get no rompe sobre un modelo poly y devuelve un dict para los campos pedidos."""
        defaults = self.env['test.test4'].default_get(['a1', 'a4', 'partner_id'])
        self.assertIsInstance(defaults, dict)

    def test_create_minimal_then_read(self):
        """create con vals mínimos ({}) crea un registro poly válido y legible."""
        t4 = self.env['test.test4'].create({})
        self.assertTrue(t4.exists())
        self.assertTrue(self.env['ir.poly_base'].browse(t4.id).exists())
        self.assertEqual(t4.concrete_model_id.model, 'test.test4')
        self.assertFalse(t4.a1)  # sin valor -> falsy

    def test_copy_single_parent_model(self):
        """copy() en jerarquía de 1 nivel (child.a): identidad nueva, datos copiados, base propia."""
        c = self.env['test.poly.child.a'].create({'base_field': 'bf', 'child_a_field': 'cf'})
        dup = c.copy()
        self.assertNotEqual(dup.id, c.id)
        self.assertEqual(dup.base_field, 'bf')
        self.assertEqual(dup.child_a_field, 'cf')
        self.assertTrue(self.env['test.poly.base'].browse(dup.id).exists())

    def test_own_m2o_set_clear_change(self):
        """m2o propio (partner_id): asignar, limpiar (False) y cambiar a otro."""
        p1 = self.env['res.partner'].create({'name': 'P1 ZZ'})
        p2 = self.env['res.partner'].create({'name': 'P2 ZZ'})
        t4 = self.env['test.test4'].create({'a1': 'a', 'partner_id': p1.id})
        self.assertEqual(t4.partner_id, p1)
        t4.partner_id = False
        t4.invalidate_recordset()
        self.assertFalse(t4.partner_id)
        t4.partner_id = p2.id
        t4.invalidate_recordset()
        self.assertEqual(t4.partner_id, p2)


@tagged('post_install', '-at_install')
class TestPolyBatchAndAggregate(TransactionCase):
    """Operaciones multi-registro y agregación: write batch, read_group SUM, dominio OR, mapped m2o."""

    MARK = '__BATCH__'

    def test_batch_write_inherited_field(self):
        """write sobre un campo heredado en un recordset de varios -> persiste en todas las bases."""
        recs = self.env['test.test4'].create([
            {'a1': 'x', 'a2': self.MARK}, {'a1': 'y', 'a2': self.MARK}, {'a1': 'z', 'a2': self.MARK}])
        recs.write({'a1': 'BATCH'})
        recs.invalidate_recordset()
        self.assertEqual(set(recs.mapped('a1')), {'BATCH'})
        for r in recs:
            self.assertEqual(self.env['test.test1'].browse(r.id).a1, 'BATCH')

    # NOTA: read_group con SUM sobre un campo INYECTADO (ej. field_b en test.poly.project) NO
    # funciona, pero es comportamiento estándar de Odoo: los campos inyectados por poly son
    # related no-stored, y Odoo no puede agregar por SQL una columna que no existe. La agrupación
    # por valor (groupby + _count) sí anda (ver test_read_group_by_inherited_field). Para sumar,
    # agregar sobre el modelo base donde el campo es stored (ej. test.poly.behavior.b.field_b).

    def test_or_domain_inherited_and_own(self):
        """Dominio OR mezclando un campo heredado (a1) y uno propio (a4)."""
        self.env['test.test4'].create({'a1': 'OX', 'a4': 'n', 'a2': self.MARK})
        self.env['test.test4'].create({'a1': 'n', 'a4': 'OW', 'a2': self.MARK})
        self.env['test.test4'].create({'a1': 'n', 'a4': 'n', 'a2': self.MARK})
        found = self.env['test.test4'].search(
            [('a2', '=', self.MARK), '|', ('a1', '=', 'OX'), ('a4', '=', 'OW')])
        self.assertEqual(len(found), 2)
        self.assertEqual(sorted(found.mapped('a1')), ['OX', 'n'])

    def test_mapped_over_own_m2o(self):
        """mapped() sobre un m2o propio (partner_id) en un recordset."""
        p1 = self.env['res.partner'].create({'name': 'M1 ZZ'})
        p2 = self.env['res.partner'].create({'name': 'M2 ZZ'})
        recs = self.env['test.test4'].create([
            {'a1': 'a', 'a2': self.MARK, 'partner_id': p1.id},
            {'a1': 'b', 'a2': self.MARK, 'partner_id': p2.id}])
        self.assertEqual(set(recs.mapped('partner_id').ids), {p1.id, p2.id})

    def test_batch_read_multi_records(self):
        """read() sobre un recordset de varios devuelve una fila por registro con sus campos."""
        recs = self.env['test.test4'].create([
            {'a1': 'r1', 'a4': 's1', 'a2': self.MARK}, {'a1': 'r2', 'a4': 's2', 'a2': self.MARK}])
        data = recs.read(['a1', 'a4'])
        by_a1 = {d['a1']: d['a4'] for d in data}
        self.assertEqual(by_a1, {'r1': 's1', 'r2': 's2'})
