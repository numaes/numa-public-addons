# -*- coding: utf-8 -*-
"""
numa_poly regression suite — the net to validate against before touching production.

Pins down with tests the expected behavior at the crossings with Odoo's ORM where poly
patches (inheritance vs override, CRUD on the diamond, inherited/overloaded fields,
concrete_model_id/as_concrete_model). Every bug found and fixed (Jun-2026) leaves its test
here so that it cannot come back in silence.

Fixture hierarchies:
  Shared-PK diamond:   test.test1 (a1,a2)
                         /            \\
                  test.test2 (a3)   test.test3 (a4)
                         \\            /
                       test.test4 (a3 overloaded, a4; set_a1 override)
  Behavior injection: test.poly.project depends on behavior.a (field_a) + behavior.b (field_b).
"""

from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestPolyMethodOverride(TransactionCase):
    """Method inheritance AND override across the poly hierarchy (MRO fix c377ea5)."""

    def test_concrete_override_wins(self):
        """The concrete's override wins over the parent's method (not the other way)."""
        t4 = self.env['test.test4'].create({'a1': 'x', 'a2': 'y', 'a3': 'z'})
        t4.set_a1()
        self.assertEqual(t4.a1, 'Set by test4',
                         "test.test4 must run ITS OWN set_a1 override, not Test1's.")

    def test_base_method_on_base(self):
        """On the base model its own method runs."""
        t1 = self.env['test.test1'].create({'a1': 'x'})
        t1.set_a1()
        self.assertEqual(t1.a1, 'Set by test1')

    def test_inherited_method_when_not_overridden(self):
        """A concrete that does NOT override inherits the parent's method (test.test2 does not)."""
        t2 = self.env['test.test2'].create({'a3': 'z'})
        t2.set_a1()
        self.assertEqual(t2.a1, 'Set by test1',
                         "test.test2 does not override set_a1 -> it inherits Test1's.")


@tagged('post_install', '-at_install')
class TestPolyDiamondCRUD(TransactionCase):
    """write / search / unlink on the diamond (test.test4). Guards the unlink bug (7ea316e)."""

    def test_write_inherited_field_persists(self):
        """Writing an inherited field (a1, from Test1) persists and reads back consistently."""
        t4 = self.env['test.test4'].create({'a1': 'C1', 'a2': 'C2', 'a3': 'C3'})
        t4.a1 = 'D1'
        t4.flush_recordset()
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'D1')
        # The value lives in the shared test1 (same id).
        self.assertEqual(self.env['test.test1'].browse(t4.id).a1, 'D1')

    def test_search_inherited_field(self):
        """Searching on an inherited field finds the diamond's record."""
        t4 = self.env['test.test4'].create({'a1': 'UNIQUE_A1', 'a2': 'b', 'a3': 'c'})
        found = self.env['test.test4'].search([('a1', '=', 'UNIQUE_A1')])
        self.assertEqual(found, t4)

    def test_search_own_field(self):
        """Searching on a field owned by the concrete (a4)."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a4': 'OWN_A4'})
        found = self.env['test.test4'].search([('a4', '=', 'OWN_A4')])
        self.assertEqual(found, t4)

    def test_unlink_cascades_all_bases(self):
        """unlink deletes the concrete AND every shared base; it never hangs."""
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
        """unlink of several diamond records at once."""
        recs = self.env['test.test4'].create([
            {'a1': 'u1', 'a3': 'p'}, {'a1': 'u2', 'a3': 'q'}, {'a1': 'u3', 'a3': 'r'}])
        ids = recs.ids
        recs.unlink()
        for tid in ids:
            self.assertFalse(self.env['test.test4'].browse(tid).exists())
            self.assertFalse(self.env['test.test1'].browse(tid).exists())

    def test_write_mixed_inherited_and_own_fields(self):
        """write touching an inherited field (a1, from Test1) and an own one (a4) at once."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a4': 'x'})
        t4.write({'a1': 'a2', 'a4': 'y'})
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'a2')
        self.assertEqual(t4.a4, 'y')
        self.assertEqual(self.env['test.test1'].browse(t4.id).a1, 'a2',
                         "The inherited field must persist in the shared base.")

    def test_overloaded_field_shares_value(self):
        """a3 is declared in Test2 and overloaded in Test4: they share the value (delegated to the same id)."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a3': 'SHARED'})
        self.assertEqual(t4.a3, 'SHARED')
        self.assertEqual(self.env['test.test2'].browse(t4.id).a3, 'SHARED',
                         "The overloaded field shares its value with the parent's (same id).")

    def test_copy_creates_new_identity_with_copied_data(self):
        """copy() creates a new id with its own ir_poly_base and copies the data (not the poly links)."""
        t4 = self.env['test.test4'].create({'a1': 'orig', 'a2': 'b', 'a3': 'c', 'a4': 'd'})
        dup = t4.copy()
        self.assertNotEqual(dup.id, t4.id, "The copy must have an identity of its own.")
        # Copied data (including what is inherited from the bases):
        self.assertEqual(dup.a1, 'orig')
        self.assertEqual(dup.a2, 'b')
        self.assertEqual(dup.a4, 'd')
        # Fresh and consistent poly identity:
        self.assertTrue(self.env['ir.poly_base'].browse(dup.id).exists(),
                        "The copy must have its own entry in ir_poly_base.")
        self.assertEqual(dup.concrete_model_id.model, 'test.test4')
        # The copy's bases are its own (same id as the copy, not the original's):
        self.assertEqual(self.env['test.test1'].browse(dup.id).a1, 'orig')
        self.assertTrue(self.env['test.test2'].browse(dup.id).exists())
        self.assertTrue(self.env['test.test3'].browse(dup.id).exists())
        # The original is left intact:
        self.assertEqual(t4.a1, 'orig')

    def test_copy_with_default_override(self):
        """copy(default=...) applies overrides over the copied data."""
        t4 = self.env['test.test4'].create({'a1': 'orig', 'a4': 'd'})
        dup = t4.copy({'a4': 'override'})
        self.assertEqual(dup.a1, 'orig', "What is not overridden gets copied.")
        self.assertEqual(dup.a4, 'override', "The default override wins.")

    def test_mapped_filtered_sorted_on_inherited_field(self):
        """mapped()/filtered()/sorted() over an inherited field in a recordset.
        This is the exact pattern that looped in unlink (mapped over PolyReference) — a guard."""
        recs = self.env['test.test4'].create([
            {'a1': 'm1', 'a2': 'M'}, {'a1': 'm2', 'a2': 'M'}, {'a1': 'm3', 'a2': 'M'}])
        self.assertEqual(sorted(recs.mapped('a1')), ['m1', 'm2', 'm3'])
        self.assertEqual(recs.filtered(lambda r: r.a1 == 'm2').a1, 'm2')
        self.assertEqual(recs.sorted('a1', reverse=True).mapped('a1'), ['m3', 'm2', 'm1'])

    def test_write_via_base_model_reflects_on_concrete(self):
        """Writing the field on the BASE model (same id) is visible from the concrete."""
        t4 = self.env['test.test4'].create({'a1': 'orig'})
        self.env['test.test1'].browse(t4.id).a1 = 'from_base'
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'from_base')


@tagged('post_install', '-at_install')
class TestPolyConcreteModel(TransactionCase):
    """concrete_model_id / as_concrete_model, and the subtype NOT storing the field (fix a70da3b)."""

    def test_concrete_model_id_value(self):
        t4 = self.env['test.test4'].create({'a1': 'a'})
        self.assertEqual(t4.concrete_model_id.model, 'test.test4')

    def test_as_concrete_model_navigates(self):
        t4 = self.env['test.test4'].create({'a1': 'a'})
        base = self.env['ir.poly_base'].browse(t4.id)
        self.assertEqual(base.as_concrete_model()._name, 'test.test4')

    def test_concrete_model_id_not_stored_on_subtype(self):
        """concrete_model_id belongs to ir.poly_base: on the subtype it must be NON-stored (computed)."""
        field = self.env['test.test4']._fields['concrete_model_id']
        self.assertFalse(field.store,
                         "concrete_model_id must not be a stored column of the subtype.")


@tagged('post_install', '-at_install')
class TestPolyBehaviorInjection(TransactionCase):
    """Behavior injection (test.poly.project: 2 _depend_models). Guards create/search/unlink."""

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
    """search (order and operators on inherited fields), batch read, display_name, read_group, m2o.
    Uses a unique marker in a2 to isolate the test's records from the rest of the table."""

    MARK = '__SRA__'  # marker for isolation (field a2, inherited from Test1)

    def _make(self, a1, a4=False):
        return self.env['test.test4'].create({'a1': a1, 'a2': self.MARK, 'a4': a4})

    def test_order_by_inherited_field(self):
        """search(order=) on an INHERITED field (a1, lives in test_test1) — pins the
        _order_field_to_sql patch in expression.py (order by a column absent from the leaf table)."""
        self._make('B'); self._make('A'); self._make('C')
        recs_asc = self.env['test.test4'].search([('a2', '=', self.MARK)], order='a1 asc')
        self.assertEqual(recs_asc.mapped('a1'), ['A', 'B', 'C'])
        recs_desc = self.env['test.test4'].search([('a2', '=', self.MARK)], order='a1 desc')
        self.assertEqual(recs_desc.mapped('a1'), ['C', 'B', 'A'])

    def test_domain_operators_on_inherited_field(self):
        """in / not in / like / != operators on an inherited field."""
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
        """Domain mixing an inherited field (a1) and an own one (a4) in the same search."""
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
        """read() of several fields (inherited a1/a2, overloaded a3, own a4) in one call."""
        t4 = self.env['test.test4'].create({'a1': 'i', 'a2': 'ii', 'a3': 'iii', 'a4': 'iv'})
        data = t4.read(['a1', 'a2', 'a3', 'a4'])[0]
        self.assertEqual(data['a1'], 'i')
        self.assertEqual(data['a2'], 'ii')
        self.assertEqual(data['a3'], 'iii')
        self.assertEqual(data['a4'], 'iv')

    def test_display_name_is_singleton_string(self):
        """display_name does not break on a poly record (no custom _rec_name: default form)."""
        t4 = self.env['test.test4'].create({'a1': 'a'})
        self.assertIsInstance(t4.display_name, str)
        self.assertTrue(t4.display_name)

    def test_own_many2one_field(self):
        """m2o field owned by the concrete (partner_id in Test4): set, read and search."""
        partner = self.env['res.partner'].create({'name': 'Poly Partner SRA'})
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': self.MARK, 'partner_id': partner.id})
        self.assertEqual(t4.partner_id, partner)
        found = self.env['test.test4'].search([('a2', '=', self.MARK), ('partner_id', '=', partner.id)])
        self.assertEqual(found, t4)

    def test_read_group_by_inherited_field(self):
        """Grouping by an inherited field (a1) counts correctly.

        [poly][20.0] read_group changed its signature and its return shape: it no
        longer takes ``fields=`` nor returns dictionaries with ``<field>_count``,
        but ``aggregates=`` and a list of tuples (models.py:1932-1940).
        """
        self._make('G1'); self._make('G1'); self._make('G2')
        groups = self.env['test.test4'].read_group(
            [('a2', '=', self.MARK)], groupby=['a1'], aggregates=['__count'])
        counts = dict(groups)
        self.assertEqual(counts.get('G1'), 2)
        self.assertEqual(counts.get('G2'), 1)


@tagged('post_install', '-at_install')
class TestPolyPolymorphicRecordset(TransactionCase):
    """The core of poly: several concretes share one base, and navigation goes base to concrete.
    Uses the hierarchy test.poly.base <- {child.a, child.b} (two concretes over the same base)."""

    def test_as_concrete_model_resolves_mixed_types(self):
        """Different concretes over the same poly base each resolve to THEIR own type."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'a', 'child_a_field': 'x'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'b', 'child_b_field': 'y'})
        base_a = self.env['ir.poly_base'].browse(ca.id)
        base_b = self.env['ir.poly_base'].browse(cb.id)
        self.assertEqual(base_a.as_concrete_model()._name, 'test.poly.child.a')
        self.assertEqual(base_b.as_concrete_model()._name, 'test.poly.child.b')
        self.assertNotEqual(ca.concrete_model_id, cb.concrete_model_id,
                            "Each concrete has its own concrete_model_id.")

    def test_shared_base_distinct_identities(self):
        """child.a and child.b share test.poly.base as their base, but have distinct ids of their own."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'A', 'child_a_field': '1'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'B', 'child_b_field': '2'})
        self.assertNotEqual(ca.id, cb.id)
        self.assertEqual(self.env['test.poly.base'].browse(ca.id).base_field, 'A')
        self.assertEqual(self.env['test.poly.base'].browse(cb.id).base_field, 'B')

    def test_single_parent_full_crud(self):
        """Full CRUD on a 1-level hierarchy (child.a -> base): create/write/search/unlink."""
        c = self.env['test.poly.child.a'].create({'base_field': 'bf', 'child_a_field': 'cf'})
        cid = c.id
        # write of an inherited field (base_field) and an own one (child_a_field) together
        c.write({'base_field': 'bf2', 'child_a_field': 'cf2'})
        c.invalidate_recordset()
        self.assertEqual(c.base_field, 'bf2')
        self.assertEqual(c.child_a_field, 'cf2')
        self.assertEqual(self.env['test.poly.base'].browse(cid).base_field, 'bf2',
                         "The inherited one persists in the shared base.")
        # search on an inherited field
        found = self.env['test.poly.child.a'].search([('base_field', '=', 'bf2')])
        self.assertEqual(found, c)
        # unlink cascades to the base
        c.unlink()
        self.assertFalse(self.env['test.poly.child.a'].browse(cid).exists())
        self.assertFalse(self.env['test.poly.base'].browse(cid).exists())

    def test_as_concrete_model_over_mixed_list(self):
        """as_concrete_model iterating over a MIXED list of ir.poly_base — the basis of the
        polymorphic rendering of lists in the UI. Each base resolves to its concrete model."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'a', 'child_a_field': 'x'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'b', 'child_b_field': 'y'})
        t4 = self.env['test.test4'].create({'a1': 'z'})
        bases = self.env['ir.poly_base'].browse([ca.id, cb.id, t4.id])
        names = [b.as_concrete_model()._name for b in bases]
        self.assertEqual(names, ['test.poly.child.a', 'test.poly.child.b', 'test.test4'])


@tagged('post_install', '-at_install')
class TestPolyLinksAndSearch(TransactionCase):
    """PolyReference links (navigating concrete->base through the link field), name_search and pagination."""

    def test_polyreference_link_navigation(self):
        """The link fields (test2_id/test3_id) point at the base record with the SAME id and give its data."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': 'b', 'a3': 'c', 'a4': 'd'})
        self.assertEqual(t4.test2_id._name, 'test.test2')
        self.assertEqual(t4.test2_id.id, t4.id, "The link shares the id (shared-PK).")
        self.assertEqual(t4.test3_id.id, t4.id)
        # a3 lives in test.test2: through the link the same value is seen.
        self.assertEqual(t4.test2_id.a3, t4.a3)

    def test_name_search_on_named_model(self):
        """name_search over a poly model with a name field (test.poly.project) filters by name."""
        self.env['test.poly.project'].create({'name': 'Alpha NS', 'field_a': '1'})
        self.env['test.poly.project'].create({'name': 'Beta NS', 'field_a': '2'})
        res = self.env['test.poly.project'].name_search('Alpha')
        names = [n for _id, n in res]
        self.assertIn('Alpha NS', names)
        self.assertNotIn('Beta NS', names)

    def test_display_name_uses_own_name_not_base(self):
        """display_name of a poly model with a name field uses ITS name, not the first base's.
        Guards the _inherits un-delegation fix on display_name (rendering of poly lists)."""
        p = self.env['test.poly.project'].create({'name': 'Proj X', 'field_a': '1'})
        self.assertEqual(p.display_name, 'Proj X',
                         "display_name must be the record's own name, not 'test.poly.behavior.a,<id>'.")

    def test_search_pagination_on_inherited_field(self):
        """limit/offset with order by an inherited field return the correct slice."""
        mark = '__PAGIN__'
        for v in ['a', 'b', 'c', 'd', 'e']:
            self.env['test.test4'].create({'a1': v, 'a2': mark})
        page = self.env['test.test4'].search(
            [('a2', '=', mark)], order='a1 asc', limit=2, offset=1)
        self.assertEqual(page.mapped('a1'), ['b', 'c'])


@tagged('post_install', '-at_install')
class TestPolyDepthDefaultsM2o(TransactionCase):
    """Base-level query (spanning concretes), 3-level chain, dotted domain through an m2o,
    default_get, minimal create, 1-level copy, and handling an own m2o (set/clear/change)."""

    def test_base_model_search_spans_concretes(self):
        """search over the BASE model finds the records of ALL its concretes.
        This is the underlying polymorphic query (a list of the base sees child.a and child.b)."""
        ca = self.env['test.poly.child.a'].create({'base_field': 'SPAN', 'child_a_field': '1'})
        cb = self.env['test.poly.child.b'].create({'base_field': 'SPAN', 'child_b_field': '2'})
        bases = self.env['test.poly.base'].search([('base_field', '=', 'SPAN')])
        self.assertEqual(set(bases.ids), {ca.id, cb.id},
                         "The base must see the records of both concretes.")

    def test_write_via_intermediate_base_propagates(self):
        """3-level chain: writing a1 on the intermediate base test.test2 (same id) is visible
        from the concrete test.test4 AND from the root test.test1."""
        t4 = self.env['test.test4'].create({'a1': 'orig'})
        self.env['test.test2'].browse(t4.id).a1 = 'via_t2'
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'via_t2')
        self.assertEqual(self.env['test.test1'].browse(t4.id).a1, 'via_t2')

    def test_dotted_domain_through_own_m2o(self):
        """Dotted domain through an own m2o: searching test4 by partner_id.name."""
        partner = self.env['res.partner'].create({'name': 'Dotted Partner ZZ'})
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': '__DOT__', 'partner_id': partner.id})
        self.env['test.test4'].create({'a1': 'b', 'a2': '__DOT__'})
        found = self.env['test.test4'].search(
            [('a2', '=', '__DOT__'), ('partner_id.name', '=', 'Dotted Partner ZZ')])
        self.assertEqual(found, t4)

    def test_default_get_returns_dict(self):
        """default_get does not break on a poly model and returns a dict for the requested fields."""
        defaults = self.env['test.test4'].default_get(['a1', 'a4', 'partner_id'])
        self.assertIsInstance(defaults, dict)

    def test_create_minimal_then_read(self):
        """create with minimal vals ({}) creates a valid, readable poly record."""
        t4 = self.env['test.test4'].create({})
        self.assertTrue(t4.exists())
        self.assertTrue(self.env['ir.poly_base'].browse(t4.id).exists())
        self.assertEqual(t4.concrete_model_id.model, 'test.test4')
        self.assertFalse(t4.a1)  # no value -> falsy

    def test_copy_single_parent_model(self):
        """copy() on a 1-level hierarchy (child.a): new identity, copied data, base of its own."""
        c = self.env['test.poly.child.a'].create({'base_field': 'bf', 'child_a_field': 'cf'})
        dup = c.copy()
        self.assertNotEqual(dup.id, c.id)
        self.assertEqual(dup.base_field, 'bf')
        self.assertEqual(dup.child_a_field, 'cf')
        self.assertTrue(self.env['test.poly.base'].browse(dup.id).exists())

    def test_own_m2o_set_clear_change(self):
        """Own m2o (partner_id): assign, clear (False) and change to another."""
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
    """Multi-record operations and aggregation: batch write, read_group SUM, OR domain, mapped m2o."""

    MARK = '__BATCH__'

    def test_batch_write_inherited_field(self):
        """write on an inherited field over a multi-record recordset -> persists in every base."""
        recs = self.env['test.test4'].create([
            {'a1': 'x', 'a2': self.MARK}, {'a1': 'y', 'a2': self.MARK}, {'a1': 'z', 'a2': self.MARK}])
        recs.write({'a1': 'BATCH'})
        recs.invalidate_recordset()
        self.assertEqual(set(recs.mapped('a1')), {'BATCH'})
        for r in recs:
            self.assertEqual(self.env['test.test1'].browse(r.id).a1, 'BATCH')

    # NOTE: read_group with SUM over an INJECTED field (e.g. field_b in test.poly.project) does
    # NOT work, but that is standard Odoo behavior: the fields poly injects are non-stored
    # related, and Odoo cannot aggregate in SQL over a column that does not exist. Grouping by
    # value (groupby + _count) does work (see test_read_group_by_inherited_field). To sum,
    # aggregate on the base model where the field is stored (e.g. test.poly.behavior.b.field_b).

    def test_or_domain_inherited_and_own(self):
        """OR domain mixing an inherited field (a1) and an own one (a4)."""
        self.env['test.test4'].create({'a1': 'OX', 'a4': 'n', 'a2': self.MARK})
        self.env['test.test4'].create({'a1': 'n', 'a4': 'OW', 'a2': self.MARK})
        self.env['test.test4'].create({'a1': 'n', 'a4': 'n', 'a2': self.MARK})
        found = self.env['test.test4'].search(
            [('a2', '=', self.MARK), '|', ('a1', '=', 'OX'), ('a4', '=', 'OW')])
        self.assertEqual(len(found), 2)
        self.assertEqual(sorted(found.mapped('a1')), ['OX', 'n'])

    def test_mapped_over_own_m2o(self):
        """mapped() over an own m2o (partner_id) in a recordset."""
        p1 = self.env['res.partner'].create({'name': 'M1 ZZ'})
        p2 = self.env['res.partner'].create({'name': 'M2 ZZ'})
        recs = self.env['test.test4'].create([
            {'a1': 'a', 'a2': self.MARK, 'partner_id': p1.id},
            {'a1': 'b', 'a2': self.MARK, 'partner_id': p2.id}])
        self.assertEqual(set(recs.mapped('partner_id').ids), {p1.id, p2.id})

    def test_batch_read_multi_records(self):
        """read() over a multi-record recordset returns one row per record with its fields."""
        recs = self.env['test.test4'].create([
            {'a1': 'r1', 'a4': 's1', 'a2': self.MARK}, {'a1': 'r2', 'a4': 's2', 'a2': self.MARK}])
        data = recs.read(['a1', 'a4'])
        by_a1 = {d['a1']: d['a4'] for d in data}
        self.assertEqual(by_a1, {'r1': 's1', 'r2': 's2'})


@tagged('post_install', '-at_install')
class TestPolyM2MAndComputed(TransactionCase):
    """Many2many and a computed-stored field on a poly model (test.test4): production patterns."""

    def _tag(self, name):
        return self.env['res.partner.category'].create({'name': name})

    def test_m2m_set_read_and_update(self):
        """Assign tags (m2m), read them, and replace the set with Command."""
        from odoo import Command
        t1, t2, t3 = self._tag('T1 ZZ'), self._tag('T2 ZZ'), self._tag('T3 ZZ')
        t4 = self.env['test.test4'].create({'a1': 'a', 'tag_ids': [Command.set([t1.id, t2.id])]})
        self.assertEqual(set(t4.tag_ids.ids), {t1.id, t2.id})
        t4.write({'tag_ids': [Command.set([t3.id])]})
        t4.invalidate_recordset()
        self.assertEqual(t4.tag_ids.ids, [t3.id])

    def test_m2m_search(self):
        """Search by the m2m (tag_ids in [...])."""
        from odoo import Command
        tag = self._tag('FindTag ZZ')
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': '__M2M__', 'tag_ids': [Command.link(tag.id)]})
        self.env['test.test4'].create({'a1': 'b', 'a2': '__M2M__'})
        found = self.env['test.test4'].search([('a2', '=', '__M2M__'), ('tag_ids', 'in', tag.id)])
        self.assertEqual(found, t4)

    def test_computed_stored_from_inherited_field(self):
        """Computed STORED (a1_upper) depending on an inherited field (a1): it is computed on
        create and RECOMPUTED when a1 changes (a1 lives in the base test.test1)."""
        t4 = self.env['test.test4'].create({'a1': 'abc'})
        self.assertEqual(t4.a1_upper, 'ABC', "It must be computed on create.")
        t4.a1 = 'xyz'
        t4.invalidate_recordset()
        self.assertEqual(t4.a1_upper, 'XYZ', "It must be recomputed when the inherited field changes.")

    def test_computed_stored_is_searchable(self):
        """The computed STORED ends up as a column -> it is searchable."""
        self.env['test.test4'].create({'a1': 'hello', 'a2': '__CMP__'})
        found = self.env['test.test4'].search([('a2', '=', '__CMP__'), ('a1_upper', '=', 'HELLO')])
        self.assertEqual(len(found), 1)


@tagged('post_install', '-at_install')
class TestPolyO2MAndConstraints(TransactionCase):
    """one2many over poly, m2o from a regular model to a poly one, and @api.constrains."""

    def test_o2m_create_with_lines(self):
        """create with line_ids (Command.create) creates the lines bound to the poly record."""
        from odoo import Command
        t4 = self.env['test.test4'].create({
            'a1': 'a',
            'line_ids': [Command.create({'name': 'L1'}), Command.create({'name': 'L2'})],
        })
        self.assertEqual(set(t4.line_ids.mapped('name')), {'L1', 'L2'})
        self.assertEqual(t4.line_ids.mapped('parent_id'), t4)

    def test_o2m_add_and_remove_lines(self):
        """write with Command.create / Command.unlink over the o2m."""
        from odoo import Command
        t4 = self.env['test.test4'].create({'a1': 'a', 'line_ids': [Command.create({'name': 'L1'})]})
        line1 = t4.line_ids
        t4.write({'line_ids': [Command.create({'name': 'L2'})]})
        t4.invalidate_recordset()
        self.assertEqual(set(t4.line_ids.mapped('name')), {'L1', 'L2'})
        t4.write({'line_ids': [Command.unlink(line1.id)]})
        t4.invalidate_recordset()
        self.assertEqual(t4.line_ids.mapped('name'), ['L2'])

    def test_m2o_from_regular_to_poly(self):
        """An m2o from a regular model pointing at a poly record resolves and allows dotted paths."""
        t4 = self.env['test.test4'].create({'a1': 'parent_a1'})
        line = self.env['test.test4.line'].create({'name': 'L', 'parent_id': t4.id})
        self.assertEqual(line.parent_id, t4)
        # dotted through the m2o to an inherited field of the poly record
        found = self.env['test.test4.line'].search([('parent_id.a1', '=', 'parent_a1')])
        self.assertIn(line, found)

    def test_unlink_poly_cascades_o2m_lines(self):
        """unlink of the poly record deletes the lines (the m2o's ondelete='cascade')."""
        from odoo import Command
        t4 = self.env['test.test4'].create({'a1': 'a', 'line_ids': [Command.create({'name': 'L1'})]})
        line_id = t4.line_ids.id
        t4.unlink()
        self.assertFalse(self.env['test.test4.line'].browse(line_id).exists())

    def test_constraint_blocks_invalid_on_create(self):
        """@api.constrains on the poly model blocks an invalid create."""
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env['test.test4'].create({'a1': 'BAD'})

    def test_constraint_blocks_invalid_on_write(self):
        """@api.constrains is evaluated on write too."""
        from odoo.exceptions import ValidationError
        t4 = self.env['test.test4'].create({'a1': 'ok'})
        with self.assertRaises(ValidationError):
            t4.a1 = 'BAD'


@tagged('post_install', '-at_install')
class TestPolyActiveArchive(TransactionCase):
    """active field / archiving on a poly model (test.test4): exclusion from the default
    search, active_test=False, toggle, and reading inherited fields while archived."""

    MARK = '__ACT__'

    def test_archived_excluded_from_default_search(self):
        """An archived record (active=False) does not show up in the default search."""
        keep = self.env['test.test4'].create({'a1': 'keep', 'a2': self.MARK})
        gone = self.env['test.test4'].create({'a1': 'gone', 'a2': self.MARK})
        gone.active = False
        found = self.env['test.test4'].search([('a2', '=', self.MARK)])
        self.assertIn(keep, found)
        self.assertNotIn(gone, found)

    def test_active_test_false_includes_archived(self):
        """With context(active_test=False) the search includes the archived ones."""
        a = self.env['test.test4'].create({'a1': 'a', 'a2': self.MARK})
        b = self.env['test.test4'].create({'a1': 'b', 'a2': self.MARK})
        b.active = False
        found = self.env['test.test4'].with_context(active_test=False).search([('a2', '=', self.MARK)])
        self.assertEqual({a.id, b.id}, set(found.ids))

    def test_search_inactive_domain(self):
        """Searching explicitly for the archived ones with [('active','=',False)]."""
        a = self.env['test.test4'].create({'a1': 'a', 'a2': self.MARK})
        b = self.env['test.test4'].create({'a1': 'b', 'a2': self.MARK})
        b.active = False
        found = self.env['test.test4'].search([('a2', '=', self.MARK), ('active', '=', False)])
        self.assertEqual(found, b)

    def test_toggle_active_roundtrip(self):
        """Archive and unarchive: it shows up again in the default search."""
        t4 = self.env['test.test4'].create({'a1': 'a', 'a2': self.MARK})
        t4.active = False
        self.assertNotIn(t4, self.env['test.test4'].search([('a2', '=', self.MARK)]))
        t4.active = True
        self.assertIn(t4, self.env['test.test4'].search([('a2', '=', self.MARK)]))

    def test_archived_record_reads_inherited_fields(self):
        """An archived record still reads its inherited fields (a1, from the base)."""
        t4 = self.env['test.test4'].create({'a1': 'inherited_val', 'a2': self.MARK})
        t4.active = False
        t4.invalidate_recordset()
        self.assertEqual(t4.a1, 'inherited_val')
        # and through the base it is still reachable
        self.assertEqual(self.env['test.test1'].browse(t4.id).a1, 'inherited_val')


@tagged('post_install', '-at_install')
class TestPolySqlConstraints(TransactionCase):
    """_sql_constraints (DB-level UNIQUE) on the leaf table of a poly model (test.test4.code)."""

    def test_sql_unique_blocks_duplicate(self):
        """Two records with the same code violate the leaf table's UNIQUE on flush."""
        self.env['test.test4'].create({'a1': 'a', 'code': 'DUP'})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.env['test.test4'].create({'a1': 'b', 'code': 'DUP'})
                self.env.flush_all()

    def test_sql_unique_allows_distinct_codes(self):
        """Distinct codes do not violate the constraint."""
        a = self.env['test.test4'].create({'a1': 'a', 'code': 'C1'})
        b = self.env['test.test4'].create({'a1': 'b', 'code': 'C2'})
        self.env.flush_all()
        self.assertTrue(a.exists() and b.exists())

    def test_sql_unique_allows_multiple_null(self):
        """Several records without code (NULL) coexist (UNIQUE allows multiple NULLs in Postgres)."""
        recs = self.env['test.test4'].create([{'a1': 'a'}, {'a1': 'b'}, {'a1': 'c'}])
        self.env.flush_all()
        self.assertEqual(len(recs), 3)

    def test_sql_unique_constraint_exists_on_leaf_table(self):
        """The UNIQUE constraint really did get created on the leaf table test_test4."""
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'test_test4'::regclass AND contype = 'u'
              AND conname LIKE %s
        """, ('%code_uniq%',))
        self.assertTrue(self.env.cr.fetchone(),
                        "The _sql_constraints must materialize as a UNIQUE on test_test4.")
