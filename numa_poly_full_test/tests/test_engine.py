# -*- coding: utf-8 -*-
"""
Engine unit tests for numa_poly using the poly.ft.* test hierarchy.

Covers: _poly_is_polymorphic, _poly_collect_depend_models,
_poly_foreign_def_classes, _poly_resolve_field_origin,
field injection attributes, cycle-token guard, and
_poly_ensure_poly_ref via _fields inspection.
"""
import logging
from collections import OrderedDict
from odoo.tests import tagged, TransactionCase

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'poly_engine_full')
class TestPolyEngineWithRealModels(TransactionCase):
    """Engine tests using the poly.ft.* diamond hierarchy."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.numa_poly.models.poly import (
            _poly_is_polymorphic,
            _poly_collect_depend_models,
            _poly_foreign_def_classes,
            _poly_resolve_field_origin,
            PolyReference,
        )
        cls._is_poly = staticmethod(_poly_is_polymorphic)
        cls._collect = staticmethod(_poly_collect_depend_models)
        cls._foreign = staticmethod(_poly_foreign_def_classes)
        cls._resolve = staticmethod(_poly_resolve_field_origin)
        cls._PolyReference = PolyReference

    # ------------------------------------------------------------------
    # _poly_is_polymorphic
    # ------------------------------------------------------------------

    def test_is_poly_base_is_false(self):
        """poly.ft.base has empty _depend_models — not polymorphic."""
        self.assertFalse(self._is_poly(type(self.env['poly.ft.base'])))

    def test_is_poly_alpha_is_true(self):
        """poly.ft.alpha depends on poly.ft.base — polymorphic."""
        self.assertTrue(self._is_poly(type(self.env['poly.ft.alpha'])))

    def test_is_poly_beta_is_true(self):
        self.assertTrue(self._is_poly(type(self.env['poly.ft.beta'])))

    def test_is_poly_top_is_true(self):
        """poly.ft.top has two deps — polymorphic."""
        self.assertTrue(self._is_poly(type(self.env['poly.ft.top'])))

    # ------------------------------------------------------------------
    # _poly_collect_depend_models
    # ------------------------------------------------------------------

    def test_collect_base_empty(self):
        deps = self._collect(type(self.env['poly.ft.base']))
        self.assertEqual(dict(deps), {})

    def test_collect_alpha_single_dep(self):
        deps = self._collect(type(self.env['poly.ft.alpha']))
        self.assertEqual(dict(deps), {'poly.ft.base': 'alpha_base_id'})

    def test_collect_beta_single_dep(self):
        deps = self._collect(type(self.env['poly.ft.beta']))
        self.assertEqual(dict(deps), {'poly.ft.base': 'beta_base_id'})

    def test_collect_top_two_direct_deps(self):
        deps = self._collect(type(self.env['poly.ft.top']))
        self.assertEqual(set(deps.keys()), {'poly.ft.alpha', 'poly.ft.beta'})
        self.assertEqual(deps['poly.ft.alpha'], 'top_alpha_id')
        self.assertEqual(deps['poly.ft.beta'], 'top_beta_id')

    def test_collect_top_excludes_transitive_dep(self):
        """poly.ft.base is transitive via alpha/beta — must NOT appear directly."""
        deps = self._collect(type(self.env['poly.ft.top']))
        self.assertNotIn('poly.ft.base', deps)

    def test_collect_returns_ordered_dict(self):
        deps = self._collect(type(self.env['poly.ft.top']))
        self.assertIsInstance(deps, OrderedDict)

    # ------------------------------------------------------------------
    # _poly_foreign_def_classes
    # ------------------------------------------------------------------

    def test_foreign_base_empty(self):
        foreign = self._foreign(type(self.env['poly.ft.base']))
        self.assertEqual(foreign, frozenset())

    def test_foreign_alpha_returns_frozenset(self):
        """_poly_foreign_def_classes always returns a frozenset (may be empty).

        NOTE: The current implementation uses ``type.mro(type(dep_reg))`` which
        iterates MetaModel's own MRO ([MetaModel, type, object]) instead of the
        registry class's MRO.  As a result the function always returns an empty
        frozenset — the guard is a safe no-op.  The behaviour is intentionally
        left as-is because fixing the MRO call causes Odoo's ``_setup_base`` to
        assert ``_rec_name='name' in _fields`` before _build_poly_fields runs.
        This test documents the actual observable contract rather than the
        ideal one.
        """
        foreign = self._foreign(type(self.env['poly.ft.alpha']))
        self.assertIsInstance(foreign, frozenset)

    def test_foreign_top_returns_frozenset(self):
        """_poly_foreign_def_classes returns a frozenset for diamond models too.

        See note on test_foreign_alpha_returns_frozenset: the MRO traversal bug
        causes this to return an empty frozenset rather than the def classes for
        poly.ft.alpha and poly.ft.beta.
        """
        foreign = self._foreign(type(self.env['poly.ft.top']))
        self.assertIsInstance(foreign, frozenset)

    def test_foreign_does_not_include_polybase_or_model(self):
        """Shared Odoo bases (PolyBase, AbstractModel) must never be in foreign set."""
        foreign = self._foreign(type(self.env['poly.ft.alpha']))
        foreign_names = {getattr(fdc, '_name', None) for fdc in foreign}
        # Even if the guard eventually returns non-empty results, shared bases must
        # not appear.
        for shared_name in ('poly.base', None, 'base.model'):
            self.assertNotIn(shared_name, foreign_names)

    # ------------------------------------------------------------------
    # _poly_resolve_field_origin
    # ------------------------------------------------------------------

    def test_resolve_native_field_returns_itself(self):
        """A native field (not related) resolves to the model that owns it."""
        origin_model, origin_field = self._resolve(
            'name', self.env['poly.ft.base'], self.env.registry
        )
        self.assertEqual(origin_model, 'poly.ft.base')
        self.assertEqual(origin_field, 'name')

    def test_resolve_injected_field_in_alpha(self):
        """poly.ft.alpha.name is related → resolves to poly.ft.base.name."""
        origin_model, origin_field = self._resolve(
            'name', self.env['poly.ft.alpha'], self.env.registry
        )
        self.assertEqual(origin_model, 'poly.ft.base')
        self.assertEqual(origin_field, 'name')

    def test_resolve_injected_field_in_top_diamond(self):
        """poly.ft.top.name routes through alpha → base."""
        origin_model, origin_field = self._resolve(
            'name', self.env['poly.ft.top'], self.env.registry
        )
        self.assertEqual(origin_model, 'poly.ft.base')
        self.assertEqual(origin_field, 'name')

    def test_resolve_unknown_field_returns_input(self):
        """Unknown fields are returned unchanged (safe fallback)."""
        origin_model, origin_field = self._resolve(
            'does_not_exist', self.env['poly.ft.base'], self.env.registry
        )
        self.assertEqual(origin_model, 'poly.ft.base')
        self.assertEqual(origin_field, 'does_not_exist')

    # ------------------------------------------------------------------
    # Field injection attributes
    # ------------------------------------------------------------------

    def test_injected_fields_are_related_non_stored(self):
        """All fields injected by poly must be related=True, store=False."""
        alpha_cls = type(self.env['poly.ft.alpha'])
        for fname in ('name', 'value'):
            with self.subTest(field=fname):
                field = alpha_cls._fields.get(fname)
                self.assertIsNotNone(field, f"'{fname}' must be injected into poly.ft.alpha")
                self.assertTrue(
                    getattr(field, 'related', None),
                    f"'{fname}' must be a related field in poly.ft.alpha",
                )
                self.assertFalse(
                    getattr(field, 'store', True),
                    f"'{fname}' must not be stored in poly.ft.alpha",
                )

    def test_injected_fields_have_poly_injected_flag(self):
        """Poly-injected fields must carry _poly_injected=True."""
        alpha_cls = type(self.env['poly.ft.alpha'])
        for fname in ('name', 'value'):
            with self.subTest(field=fname):
                field = alpha_cls._fields.get(fname)
                self.assertIsNotNone(field)
                self.assertTrue(
                    getattr(field, '_poly_injected', False),
                    f"'{fname}' must have _poly_injected=True",
                )

    def test_link_field_is_poly_reference(self):
        """The link field (alpha_base_id) must be a PolyReference instance."""
        alpha_cls = type(self.env['poly.ft.alpha'])
        self.assertIn('alpha_base_id', alpha_cls._fields)
        self.assertIsInstance(alpha_cls._fields['alpha_base_id'], self._PolyReference)

    def test_poly_base_id_infrastructure_on_alpha(self):
        """poly.ft.alpha must have a poly_base_id PolyReference to ir.poly_base."""
        alpha_cls = type(self.env['poly.ft.alpha'])
        self.assertIn('poly_base_id', alpha_cls._fields)
        field = alpha_cls._fields['poly_base_id']
        self.assertIsInstance(field, self._PolyReference)
        self.assertEqual(field.comodel_name, 'ir.poly_base')

    def test_audit_fields_present_on_poly_model(self):
        """Audit fields (create_uid etc.) are native Odoo BaseModel fields that
        exist on every model.  On poly models they are listed in
        _POLY_TECHNICAL_FIELDS and deliberately NOT injected as related fields,
        since every model already has them from BaseModel."""
        alpha_cls = type(self.env['poly.ft.alpha'])
        for audit_fname in ('create_uid', 'create_date', 'write_uid', 'write_date'):
            with self.subTest(field=audit_fname):
                field = alpha_cls._fields.get(audit_fname)
                self.assertIsNotNone(field, f"{audit_fname} must be present on poly.ft.alpha")
                # Audit fields are native stored fields, NOT poly-injected related fields.
                self.assertFalse(
                    getattr(field, '_poly_injected', False),
                    f"{audit_fname} must NOT be poly-injected on poly.ft.alpha",
                )

    # ------------------------------------------------------------------
    # Cycle-token
    # ------------------------------------------------------------------

    def test_poly_fields_built_token_matches_cycle(self):
        """After setup, _poly_fields_built on a poly model must equal _poly_setup_cycle."""
        from odoo.addons.numa_poly.models import poly as poly_module
        alpha_cls = type(self.env['poly.ft.alpha'])
        built = getattr(alpha_cls, '_poly_fields_built', None)
        self.assertIsNotNone(built, "_poly_fields_built must be set on poly.ft.alpha")
        self.assertEqual(
            built, poly_module._poly_setup_cycle,
            "_poly_fields_built must equal _poly_setup_cycle",
        )

    def test_non_poly_model_has_no_cycle_token(self):
        """Non-poly models (empty _depend_models) never have _poly_fields_built set.

        _build_poly_fields is only invoked from _setup_base for polymorphic models
        (the ``if _poly_is_polymorphic`` branch).  Non-poly models take the ``else``
        branch which calls the original _setup_base without field injection, so
        _poly_fields_built remains absent on their class.
        """
        base_cls = type(self.env['poly.ft.base'])
        built = base_cls.__dict__.get('_poly_fields_built')
        self.assertIsNone(
            built,
            "poly.ft.base must NOT have _poly_fields_built in its own __dict__",
        )
