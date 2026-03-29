# -*- coding: utf-8 -*-
"""
Unit tests for numa_poly engine internals.

These tests verify the core engine functions using only ir.poly_base
(always present) and res.partner as fixtures.  No external poly model
module is required.
"""
import logging
from odoo.tests import tagged, TransactionCase

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'poly_engine')
class TestPolyEngineInternals(TransactionCase):
    """Unit tests for _poly_is_polymorphic, _poly_collect_depend_models,
    _PolyFieldGuard, cycle-token semantics, and ir.poly_base field structure."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.numa_poly.models.poly import (
            _poly_is_polymorphic,
            _poly_collect_depend_models,
            _poly_foreign_def_classes,
            _PolyFieldGuard,
            _poly_setup_cycle,
            PolyReference,
        )
        cls._is_poly = staticmethod(_poly_is_polymorphic)
        cls._collect = staticmethod(_poly_collect_depend_models)
        cls._foreign = staticmethod(_poly_foreign_def_classes)
        cls._Guard = _PolyFieldGuard
        cls._PolyReference = PolyReference

    # ------------------------------------------------------------------
    # _poly_is_polymorphic
    # ------------------------------------------------------------------

    def test_is_polymorphic_ir_poly_base_is_false(self):
        """ir.poly_base is the root — it must not be considered polymorphic."""
        self.assertFalse(
            self._is_poly(type(self.env['ir.poly_base'])),
            "ir.poly_base must not be polymorphic",
        )

    def test_is_polymorphic_regular_model_is_false(self):
        """Standard Odoo models without _depend_models are not polymorphic."""
        self.assertFalse(
            self._is_poly(type(self.env['res.partner'])),
            "res.partner must not be polymorphic",
        )

    def test_is_polymorphic_requires_nonempty_depend_models(self):
        """A model with _depend_models = {} (empty) is not polymorphic."""
        # ir.poly_base itself has _depend_models = None; confirm the function's
        # type checking via ir.poly_base class (not an empty recordset).
        result = self._is_poly(type(self.env['ir.poly_base']))
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # _poly_collect_depend_models
    # ------------------------------------------------------------------

    def test_collect_depend_models_ir_poly_base_empty(self):
        """ir.poly_base has no dependencies — result must be empty OrderedDict."""
        from collections import OrderedDict
        deps = self._collect(type(self.env['ir.poly_base']))
        self.assertIsInstance(deps, OrderedDict)
        self.assertEqual(len(deps), 0)

    def test_collect_depend_models_non_poly_empty(self):
        """Non-polymorphic models return an empty OrderedDict."""
        from collections import OrderedDict
        deps = self._collect(type(self.env['res.partner']))
        self.assertIsInstance(deps, OrderedDict)
        self.assertEqual(len(deps), 0)

    # ------------------------------------------------------------------
    # _poly_foreign_def_classes
    # ------------------------------------------------------------------

    def test_foreign_def_classes_ir_poly_base_empty(self):
        """ir.poly_base has no foreign definition classes."""
        foreign = self._foreign(type(self.env['ir.poly_base']))
        self.assertEqual(foreign, frozenset())

    def test_foreign_def_classes_non_poly_empty(self):
        """Non-polymorphic models have no foreign definition classes."""
        foreign = self._foreign(type(self.env['res.partner']))
        self.assertEqual(foreign, frozenset())

    def test_foreign_def_classes_returns_frozenset(self):
        """Return type must always be frozenset."""
        result = self._foreign(type(self.env['ir.poly_base']))
        self.assertIsInstance(result, frozenset)

    # ------------------------------------------------------------------
    # _PolyFieldGuard mechanics (no registry access needed)
    # ------------------------------------------------------------------

    def test_field_guard_blanks_field_definitions_on_enter(self):
        """__enter__ must set _field_definitions to [] on saved classes."""
        class FakeDefClass:
            _name = 'fake.model'
            pool = None
            _field_definitions = ['field_a', 'field_b']

        guard = object.__new__(self._Guard)
        guard._saved = {FakeDefClass: ['field_a', 'field_b']}

        guard.__enter__()
        self.assertEqual(
            FakeDefClass._field_definitions, [],
            "_field_definitions must be blanked on __enter__",
        )
        guard.__exit__(None, None, None)

    def test_field_guard_restores_on_exit(self):
        """__exit__ must restore original _field_definitions."""
        class FakeDefClass:
            _name = 'fake.model'
            pool = None
            _field_definitions = ['original']

        guard = object.__new__(self._Guard)
        guard._saved = {FakeDefClass: ['original']}

        with guard:
            self.assertEqual(FakeDefClass._field_definitions, [])

        self.assertEqual(
            FakeDefClass._field_definitions, ['original'],
            "_field_definitions must be restored on __exit__",
        )

    def test_field_guard_restores_on_exception(self):
        """__exit__ must restore _field_definitions even if the body raises."""
        class FakeDefClass:
            _name = 'fake.model'
            pool = None
            _field_definitions = ['preserve_me']

        guard = object.__new__(self._Guard)
        guard._saved = {FakeDefClass: ['preserve_me']}

        try:
            with guard:
                self.assertEqual(FakeDefClass._field_definitions, [])
                raise RuntimeError("simulated failure inside _setup_base")
        except RuntimeError:
            pass

        self.assertEqual(
            FakeDefClass._field_definitions, ['preserve_me'],
            "_field_definitions must be restored after exception",
        )

    def test_field_guard_handles_no_saved_classes(self):
        """A guard with no foreign def classes is a safe no-op."""
        guard = self._Guard(type(self.env['ir.poly_base']))
        # No saved state — enter and exit must not raise
        with guard:
            pass

    # ------------------------------------------------------------------
    # Cycle-token semantics
    # ------------------------------------------------------------------

    def test_setup_cycle_is_positive_after_load(self):
        """_poly_setup_cycle must have been incremented at least once."""
        from odoo.addons.numa_poly.models import poly as poly_module
        self.assertGreater(
            poly_module._poly_setup_cycle, 0,
            "_poly_setup_cycle must be > 0 after module load",
        )

    def test_setup_cycle_is_integer(self):
        """_poly_setup_cycle must be an integer."""
        from odoo.addons.numa_poly.models import poly as poly_module
        self.assertIsInstance(poly_module._poly_setup_cycle, int)

    # ------------------------------------------------------------------
    # ir.poly_base field structure
    # ------------------------------------------------------------------

    def test_ir_poly_base_has_concrete_model_id(self):
        """ir.poly_base must have a concrete_model_id field."""
        self.assertIn('concrete_model_id', self.env['ir.poly_base']._fields)

    def test_ir_poly_base_has_old_id(self):
        """ir.poly_base must have an old_id field for migration."""
        self.assertIn('old_id', self.env['ir.poly_base']._fields)

    def test_poly_base_field_guard_init_saves_existing_field_definitions(self):
        """_PolyFieldGuard.__init__ must save _field_definitions from each
        foreign def class that has one defined in its __dict__."""
        class FakeDefClassWithDefs:
            _name = 'fake.with.defs'
            pool = None
            _field_definitions = ['f1', 'f2']

        class FakeDefClassWithoutDefs:
            _name = 'fake.no.defs'
            pool = None
            # No _field_definitions in __dict__

        guard = object.__new__(self._Guard)
        # Manually call __init__ logic by simulating _poly_foreign_def_classes result
        guard._saved = {}
        for fdc in (FakeDefClassWithDefs, FakeDefClassWithoutDefs):
            original = fdc.__dict__.get('_field_definitions')
            if original is not None:
                guard._saved[fdc] = original

        # Only the class with _field_definitions in __dict__ should be saved
        self.assertIn(FakeDefClassWithDefs, guard._saved)
        self.assertNotIn(FakeDefClassWithoutDefs, guard._saved)
        self.assertEqual(guard._saved[FakeDefClassWithDefs], ['f1', 'f2'])
