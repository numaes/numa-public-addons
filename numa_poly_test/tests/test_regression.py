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
