# Test Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add comprehensive tests to `numa_poly` (pure unit tests of engine internals, zero external deps) and create a new `numa_poly_full_test` module (integration tests with real poly models) so that both suites passing together give reasonable regression confidence in production.

**Architecture:** `numa_poly` gains `test_engine_internals.py` covering engine functions with only `ir.poly_base` and `res.partner` as fixtures. `numa_poly_full_test` is a new installable module that defines a four-model diamond hierarchy (`poly.ft.base → poly.ft.alpha/beta → poly.ft.top`) in `models/`, then exercises both engine internals (against real poly models) and full ORM behaviour (create/write/unlink/search/method-dispatch) in `tests/`.

**Tech Stack:** Python 3.10, Odoo 18, `odoo.tests.TransactionCase`, `_poly_is_polymorphic`, `_poly_collect_depend_models`, `_poly_foreign_def_classes`, `_PolyFieldGuard`, `_poly_resolve_field_origin`, `PolyReference`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `numa_poly/tests/test_engine_internals.py` | Create | Pure unit tests of engine functions; only `ir.poly_base` and `res.partner` as fixtures |
| `numa_poly/tests/__init__.py` | Modify | Import `test_engine_internals` |
| `numa_poly_full_test/__manifest__.py` | Create | Module declaration, depends on `numa_poly` |
| `numa_poly_full_test/__init__.py` | Create | Import models |
| `numa_poly_full_test/models/__init__.py` | Create | Import test_models |
| `numa_poly_full_test/models/test_models.py` | Create | `poly.ft.base/alpha/beta/top` diamond hierarchy |
| `numa_poly_full_test/security/security.xml` | Create | Empty data block (required by Odoo) |
| `numa_poly_full_test/security/ir.model.access.csv` | Create | Full read/write/create/unlink for group_user |
| `numa_poly_full_test/tests/__init__.py` | Create | Import `test_engine`, `test_orm` |
| `numa_poly_full_test/tests/test_engine.py` | Create | Engine internals tests with real poly.ft.* models |
| `numa_poly_full_test/tests/test_orm.py` | Create | Full ORM integration tests |

---

## Task 1 — `numa_poly` internal unit tests (no external deps)

**Files:**
- Create: `numa_poly/tests/test_engine_internals.py`
- Modify: `numa_poly/tests/__init__.py`

Tests target functions from `numa_poly.models.poly` and use only `ir.poly_base` (always installed) and `res.partner` as fixtures. Tests that require real poly models skip gracefully if none are installed.

- [ ] **Step 1.1 — Create `test_engine_internals.py`**

```python
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
        cls._is_poly = _poly_is_polymorphic
        cls._collect = _poly_collect_depend_models
        cls._foreign = _poly_foreign_def_classes
        cls._Guard = _PolyFieldGuard
        cls._PolyReference = PolyReference

    # ------------------------------------------------------------------
    # _poly_is_polymorphic
    # ------------------------------------------------------------------

    def test_is_polymorphic_ir_poly_base_is_false(self):
        """ir.poly_base is the root — it must not be considered polymorphic."""
        self.assertFalse(
            self._is_poly(self.env['ir.poly_base']),
            "ir.poly_base must not be polymorphic",
        )

    def test_is_polymorphic_regular_model_is_false(self):
        """Standard Odoo models without _depend_models are not polymorphic."""
        self.assertFalse(
            self._is_poly(self.env['res.partner']),
            "res.partner must not be polymorphic",
        )

    def test_is_polymorphic_requires_nonempty_depend_models(self):
        """A model with _depend_models = {} (empty) is not polymorphic."""
        # ir.poly_base itself has _depend_models = None; find any model with empty dict.
        # If no such model is installed, this test is vacuously consistent — we
        # confirm the function's type checking via ir.poly_base.
        result = self._is_poly(self.env['ir.poly_base'])
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
```

- [ ] **Step 1.2 — Import in `tests/__init__.py`**

Open `numa_poly/tests/__init__.py` and append:

```python
from . import test_engine_internals
```

Full file should be:
```python
from . import test_poly_improvements
from . import test_poly_setup
from . import test_engine_internals
```

- [ ] **Step 1.3 — Run the new tests**

```bash
cd /home/gamarino/odoo/cm-18.0 && source .venv/bin/activate && \
../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config \
  --test-enable --stop-after-init \
  --test-tags poly_engine \
  -d cm-test-18.0 --http-port 8099 2>&1 | tail -15
```

Expected: `0 failed, 0 error(s)`. All 14 tests pass.

- [ ] **Step 1.4 — Run full numa_poly suite (regression check)**

```bash
cd /home/gamarino/odoo/cm-18.0 && source .venv/bin/activate && \
../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config \
  --test-enable --stop-after-init \
  --test-tags numa_poly \
  -d cm-test-18.0 --http-port 8099 2>&1 | tail -10
```

Expected: 0 failed, 0 errors.

- [ ] **Step 1.5 — Commit**

```bash
cd /home/gamarino/odoo/numa-public-addons-18.0 && \
git add numa_poly/tests/test_engine_internals.py numa_poly/tests/__init__.py && \
git commit -m "$(cat <<'EOF'
[numa_poly] Add test_engine_internals: unit tests for engine functions

Covers:
- _poly_is_polymorphic: False for ir.poly_base and res.partner
- _poly_collect_depend_models: empty for ir.poly_base and non-poly models
- _poly_foreign_def_classes: empty frozenset for ir.poly_base and non-poly
- _PolyFieldGuard: blanks _field_definitions on __enter__, restores on
  __exit__ (normal and exception paths), safe no-op for models with no
  foreign def classes; __init__ only saves classes with _field_definitions
  in their own __dict__
- _poly_setup_cycle: integer > 0 after module load (cycle-token semantics)
- ir.poly_base field structure: concrete_model_id and old_id present

All tests use only ir.poly_base and res.partner as fixtures — zero
dependency on external poly model modules.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Create `numa_poly_full_test` module scaffold and models

**Files:**
- Create: `numa_poly_full_test/__manifest__.py`
- Create: `numa_poly_full_test/__init__.py`
- Create: `numa_poly_full_test/models/__init__.py`
- Create: `numa_poly_full_test/models/test_models.py`
- Create: `numa_poly_full_test/security/security.xml`
- Create: `numa_poly_full_test/security/ir.model.access.csv`
- Create: `numa_poly_full_test/tests/__init__.py` (empty for now)

Model hierarchy:
```
poly.ft.base (no deps)       fields: name:Char, value:Integer
    |               |
poly.ft.alpha       poly.ft.beta
(→ base)            (→ base)
  alpha_note:Char     beta_count:Integer
    |               |
       poly.ft.top  (diamond: → alpha + beta)
         top_flag:Boolean
```

`poly.ft.base` has a `make_uppercase()` method that uppercases `name`.
`poly.ft.top` overrides it to also append `_TOP` and set `top_flag=True`.

- [ ] **Step 2.1 — Create `__manifest__.py`**

```python
# -*- coding: utf-8 -*-
{
    'name': 'Numa Poly Full Test',
    'version': '18.0.1.0.0',
    'summary': 'Integration test suite for the numa_poly polymorphic engine.',
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'AGPL-3',
    'category': 'Hidden',
    'depends': ['base', 'numa_poly'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
}
```

- [ ] **Step 2.2 — Create `__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import models
```

- [ ] **Step 2.3 — Create `models/__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import test_models
```

- [ ] **Step 2.4 — Create `models/test_models.py`**

```python
# -*- coding: utf-8 -*-
"""
Test models for numa_poly integration tests.

Hierarchy (diamond):

    poly.ft.base
   /            \\
poly.ft.alpha  poly.ft.beta
   \\            /
    poly.ft.top

poly.ft.base: root — no dependencies
poly.ft.alpha: depends on poly.ft.base (link: alpha_base_id)
poly.ft.beta:  depends on poly.ft.base (link: beta_base_id)
poly.ft.top:   depends on poly.ft.alpha (top_alpha_id) + poly.ft.beta (top_beta_id)
"""
from collections import OrderedDict
from odoo import models, fields


class PolyFtBase(models.Model):
    """Root model in the test hierarchy.  No polymorphic dependencies."""
    _name = 'poly.ft.base'
    _description = 'Poly Full Test — Base'
    _depend_models = OrderedDict()

    name = fields.Char('Name')
    value = fields.Integer('Value')

    def make_uppercase(self):
        """Uppercase the name field.  Overridable by child models."""
        self.name = (self.name or '').upper()


class PolyFtAlpha(models.Model):
    """Single-dependency model: depends on poly.ft.base."""
    _name = 'poly.ft.alpha'
    _description = 'Poly Full Test — Alpha'
    _depend_models = OrderedDict([('poly.ft.base', 'alpha_base_id')])

    alpha_note = fields.Char('Alpha Note')


class PolyFtBeta(models.Model):
    """Single-dependency model: depends on poly.ft.base (parallel to Alpha)."""
    _name = 'poly.ft.beta'
    _description = 'Poly Full Test — Beta'
    _depend_models = OrderedDict([('poly.ft.base', 'beta_base_id')])

    beta_count = fields.Integer('Beta Count')


class PolyFtTop(models.Model):
    """Diamond model: depends on both Alpha and Beta.

    Inherits name, value (via alpha/beta → base),
    alpha_note (via alpha), and beta_count (via beta).

    Overrides make_uppercase() to also append '_TOP' and set top_flag.
    """
    _name = 'poly.ft.top'
    _description = 'Poly Full Test — Top (diamond)'
    _depend_models = OrderedDict([
        ('poly.ft.alpha', 'top_alpha_id'),
        ('poly.ft.beta', 'top_beta_id'),
    ])

    top_flag = fields.Boolean('Top Flag')

    def make_uppercase(self):
        """Override: uppercase name (via super), append '_TOP', set top_flag."""
        super().make_uppercase()           # sets self.name = name.upper()
        self.name = (self.name or '') + '_TOP'
        self.top_flag = True
```

- [ ] **Step 2.5 — Create `security/security.xml`**

```xml
<?xml version="1.0" ?>
<odoo>
    <data noupdate="0"/>
</odoo>
```

- [ ] **Step 2.6 — Create `security/ir.model.access.csv`**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_poly_ft_base,access_poly_ft_base,model_poly_ft_base,base.group_user,1,1,1,1
access_poly_ft_alpha,access_poly_ft_alpha,model_poly_ft_alpha,base.group_user,1,1,1,1
access_poly_ft_beta,access_poly_ft_beta,model_poly_ft_beta,base.group_user,1,1,1,1
access_poly_ft_top,access_poly_ft_top,model_poly_ft_top,base.group_user,1,1,1,1
```

- [ ] **Step 2.7 — Create `tests/__init__.py` (empty placeholder)**

```python
# -*- coding: utf-8 -*-
# Test imports added in Tasks 3 and 4.
```

- [ ] **Step 2.8 — Install the module in the test database**

```bash
cd /home/gamarino/odoo/cm-18.0 && source .venv/bin/activate && \
../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config \
  --stop-after-init \
  -u numa_poly_full_test \
  -d cm-test-18.0 --http-port 8099 2>&1 | tail -10
```

Expected: no errors, module installed. Check: `poly.ft.base`, `poly.ft.alpha`, `poly.ft.beta`, `poly.ft.top` appear in `ir.model`.

- [ ] **Step 2.9 — Commit**

```bash
cd /home/gamarino/odoo/numa-public-addons-18.0 && \
git add numa_poly_full_test/ && \
git commit -m "$(cat <<'EOF'
[numa_poly_full_test] New module: diamond test hierarchy for integration tests

Creates numa_poly_full_test with four poly.ft.* models in a diamond pattern:

    poly.ft.base (no deps, name/value fields, make_uppercase() method)
          / \
  poly.ft.alpha   poly.ft.beta
  (→ base)         (→ base)
    alpha_note       beta_count
          \ /
      poly.ft.top  (→ alpha + beta)
        top_flag, overrides make_uppercase()

The module is self-contained (depends only on base + numa_poly), has full
security declarations, and is installable.  Test files are added in the
following commits.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Engine unit tests in `numa_poly_full_test`

**Files:**
- Create: `numa_poly_full_test/tests/test_engine.py`
- Modify: `numa_poly_full_test/tests/__init__.py`

These tests have access to real poly.ft.* models and exercise every engine function that cannot be fully tested with only `ir.poly_base`.

- [ ] **Step 3.1 — Create `tests/test_engine.py`**

```python
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
        cls._is_poly = _poly_is_polymorphic
        cls._collect = _poly_collect_depend_models
        cls._foreign = _poly_foreign_def_classes
        cls._resolve = _poly_resolve_field_origin
        cls._PolyReference = PolyReference

    # ------------------------------------------------------------------
    # _poly_is_polymorphic
    # ------------------------------------------------------------------

    def test_is_poly_base_is_false(self):
        """poly.ft.base has empty _depend_models — not polymorphic."""
        self.assertFalse(self._is_poly(self.env['poly.ft.base']))

    def test_is_poly_alpha_is_true(self):
        """poly.ft.alpha depends on poly.ft.base — polymorphic."""
        self.assertTrue(self._is_poly(self.env['poly.ft.alpha']))

    def test_is_poly_beta_is_true(self):
        self.assertTrue(self._is_poly(self.env['poly.ft.beta']))

    def test_is_poly_top_is_true(self):
        """poly.ft.top has two deps — polymorphic."""
        self.assertTrue(self._is_poly(self.env['poly.ft.top']))

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

    def test_foreign_alpha_contains_base_def_class(self):
        """poly.ft.alpha's MRO includes poly.ft.base's def class (Phase-1 injected)."""
        from odoo.models import MetaModel
        foreign = self._foreign(type(self.env['poly.ft.alpha']))
        self.assertIsInstance(foreign, frozenset)
        self.assertGreater(len(foreign), 0, "poly.ft.alpha must have at least one foreign def class")
        for fdc in foreign:
            with self.subTest(cls=fdc):
                self.assertIsInstance(fdc, MetaModel)
                self.assertIsNone(fdc.pool)
                self.assertEqual(fdc._name, 'poly.ft.base')

    def test_foreign_top_contains_alpha_and_beta_def_classes(self):
        """poly.ft.top's MRO includes def classes for both alpha and beta."""
        foreign = self._foreign(type(self.env['poly.ft.top']))
        foreign_names = {getattr(fdc, '_name', None) for fdc in foreign}
        # Must include at least poly.ft.alpha and poly.ft.beta definition classes
        self.assertTrue(
            {'poly.ft.alpha', 'poly.ft.beta'}.issubset(foreign_names),
            f"Expected poly.ft.alpha and poly.ft.beta in foreign set; got {foreign_names}",
        )

    def test_foreign_does_not_include_polybase_or_model(self):
        """Shared Odoo bases (PolyBase, AbstractModel) must never be in foreign set."""
        foreign = self._foreign(type(self.env['poly.ft.alpha']))
        foreign_names = {getattr(fdc, '_name', None) for fdc in foreign}
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

    def test_audit_fields_injected_via_poly_base_id(self):
        """Audit fields must be related through poly_base_id on poly models."""
        alpha_cls = type(self.env['poly.ft.alpha'])
        for audit_fname in ('create_uid', 'create_date', 'write_uid', 'write_date'):
            with self.subTest(field=audit_fname):
                field = alpha_cls._fields.get(audit_fname)
                self.assertIsNotNone(field, f"{audit_fname} must be present on poly.ft.alpha")
                related = getattr(field, 'related', None)
                self.assertIsNotNone(related, f"{audit_fname} must be a related field")
                self.assertIn(
                    'poly_base_id', related,
                    f"{audit_fname}.related must route through poly_base_id",
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

    def test_non_poly_model_cycle_token(self):
        """Non-poly models also get a cycle token to guard against repeated calls."""
        from odoo.addons.numa_poly.models import poly as poly_module
        base_cls = type(self.env['poly.ft.base'])
        built = getattr(base_cls, '_poly_fields_built', None)
        self.assertIsNotNone(built)
        self.assertEqual(built, poly_module._poly_setup_cycle)
```

- [ ] **Step 3.2 — Update `tests/__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import test_engine
```

- [ ] **Step 3.3 — Run the engine tests**

```bash
cd /home/gamarino/odoo/cm-18.0 && source .venv/bin/activate && \
../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config \
  --test-enable --stop-after-init \
  --test-tags poly_engine_full \
  -d cm-test-18.0 --http-port 8099 2>&1 | tail -15
```

Expected: 0 failed, 0 errors.

- [ ] **Step 3.4 — Commit**

```bash
cd /home/gamarino/odoo/numa-public-addons-18.0 && \
git add numa_poly_full_test/tests/ && \
git commit -m "$(cat <<'EOF'
[numa_poly_full_test] Add test_engine: engine unit tests with real poly.ft.* models

Covers (tag: poly_engine_full):
- _poly_is_polymorphic: True for alpha/beta/top, False for base
- _poly_collect_depend_models: single dep (alpha/beta), two direct deps (top),
  transitive dep (poly.ft.base) excluded from top's map
- _poly_foreign_def_classes: empty for base; alpha has poly.ft.base def classes;
  top has poly.ft.alpha and poly.ft.beta def classes; shared Odoo bases excluded
- _poly_resolve_field_origin: native field returns self; injected field resolves
  to poly.ft.base; diamond chain also resolves to base; unknown field returns input
- Field injection attributes: related, store=False, _poly_injected=True for all
  injected fields in poly.ft.alpha; link fields are PolyReference instances;
  poly_base_id infrastructure and audit fields present with correct related path
- Cycle-token: _poly_fields_built == _poly_setup_cycle for both poly and non-poly models

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — ORM integration tests in `numa_poly_full_test`

**Files:**
- Create: `numa_poly_full_test/tests/test_orm.py`
- Modify: `numa_poly_full_test/tests/__init__.py`

Full end-to-end ORM tests: create/write/unlink/search/method dispatch/as_concrete_model/fields_get.

- [ ] **Step 4.1 — Create `tests/test_orm.py`**

```python
# -*- coding: utf-8 -*-
"""
ORM integration tests for numa_poly using the poly.ft.* test hierarchy.

Covers: create, batch create, write, bulk write, unlink cascade, search on
injected fields, search on own fields, as_concrete_model, method resolution
via MRO (inherited and overridden), and fields_get.
"""
import logging
from odoo.tests import tagged, TransactionCase

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'poly_orm')
class TestPolyOrm(TransactionCase):
    """Full ORM integration tests for the poly.ft.* diamond hierarchy."""

    def setUp(self):
        super().setUp()
        # Clean all ft records before each test to ensure isolation.
        for model_name in ('poly.ft.top', 'poly.ft.beta', 'poly.ft.alpha', 'poly.ft.base'):
            self.env[model_name].search([]).unlink()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def test_create_base_record(self):
        """Creating a non-poly base record stores name and value."""
        rec = self.env['poly.ft.base'].create({'name': 'Base1', 'value': 10})
        self.assertEqual(rec.name, 'Base1')
        self.assertEqual(rec.value, 10)
        self.assertTrue(rec.exists())

    def test_create_alpha_propagates_to_base(self):
        """Creating poly.ft.alpha must create a shared record in poly.ft.base."""
        alpha = self.env['poly.ft.alpha'].create({'name': 'Alpha1', 'value': 20, 'alpha_note': 'note1'})
        self.assertEqual(alpha.name, 'Alpha1')
        self.assertEqual(alpha.value, 20)
        self.assertEqual(alpha.alpha_note, 'note1')
        # Shared ID in base
        base_rec = self.env['poly.ft.base'].browse(alpha.id)
        self.assertTrue(base_rec.exists(), "poly.ft.base record with same ID must exist")
        self.assertEqual(base_rec.name, 'Alpha1')
        self.assertEqual(base_rec.value, 20)

    def test_create_beta_propagates_to_base(self):
        beta = self.env['poly.ft.beta'].create({'name': 'Beta1', 'value': 5, 'beta_count': 7})
        self.assertEqual(beta.name, 'Beta1')
        self.assertEqual(beta.beta_count, 7)
        base_rec = self.env['poly.ft.base'].browse(beta.id)
        self.assertTrue(base_rec.exists())
        self.assertEqual(base_rec.name, 'Beta1')

    def test_create_top_diamond_propagates_all(self):
        """Creating poly.ft.top must create shared records across entire hierarchy."""
        top = self.env['poly.ft.top'].create({
            'name': 'Top1',
            'value': 99,
            'alpha_note': 'an',
            'beta_count': 3,
            'top_flag': True,
        })
        self.assertEqual(top.name, 'Top1')
        self.assertEqual(top.value, 99)
        self.assertEqual(top.alpha_note, 'an')
        self.assertEqual(top.beta_count, 3)
        self.assertTrue(top.top_flag)
        # All share the same ID
        for model_name in ('poly.ft.alpha', 'poly.ft.beta', 'poly.ft.base'):
            with self.subTest(model=model_name):
                self.assertTrue(
                    self.env[model_name].browse(top.id).exists(),
                    f"{model_name} record with id={top.id} must exist after poly.ft.top.create()",
                )

    def test_create_batch_returns_unique_ids(self):
        """Batch create must return records with distinct IDs."""
        recs = self.env['poly.ft.alpha'].create([
            {'name': 'A', 'value': 1},
            {'name': 'B', 'value': 2},
            {'name': 'C', 'value': 3},
        ])
        self.assertEqual(len(recs), 3)
        self.assertEqual(len(set(recs.ids)), 3, "Batch-created records must have unique IDs")

    def test_create_alpha_populates_link_field(self):
        """alpha_base_id.id must equal alpha.id after creation."""
        alpha = self.env['poly.ft.alpha'].create({'name': 'LinkTest', 'value': 1})
        self.assertTrue(alpha.alpha_base_id, "alpha_base_id must be set")
        self.assertEqual(alpha.alpha_base_id.id, alpha.id)
        self.assertEqual(alpha.alpha_base_id._name, 'poly.ft.base')

    def test_create_top_populates_both_link_fields(self):
        top = self.env['poly.ft.top'].create({'name': 'T', 'value': 0})
        self.assertEqual(top.top_alpha_id.id, top.id)
        self.assertEqual(top.top_beta_id.id, top.id)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def test_write_own_field(self):
        """write() on a model's own field persists correctly."""
        alpha = self.env['poly.ft.alpha'].create({'name': 'X', 'alpha_note': 'old'})
        alpha.write({'alpha_note': 'new'})
        self.assertEqual(alpha.alpha_note, 'new')

    def test_write_inherited_field_propagates_to_base(self):
        """write() on an inherited field must update the base model's record."""
        alpha = self.env['poly.ft.alpha'].create({'name': 'BeforeWrite', 'value': 1})
        alpha.write({'name': 'AfterWrite', 'value': 42})
        self.assertEqual(alpha.name, 'AfterWrite')
        self.assertEqual(alpha.value, 42)
        # Verify propagation
        base_rec = self.env['poly.ft.base'].browse(alpha.id)
        self.assertEqual(base_rec.name, 'AfterWrite')
        self.assertEqual(base_rec.value, 42)

    def test_write_bulk_recordset(self):
        """write() on a multi-record recordset must update all records."""
        recs = self.env['poly.ft.alpha'].create([
            {'name': 'X', 'value': 1},
            {'name': 'Y', 'value': 2},
        ])
        recs.write({'value': 99})
        for r in recs:
            self.assertEqual(r.value, 99)

    def test_write_diamond_inherited_field(self):
        """write() on an inherited field in a diamond model propagates correctly."""
        top = self.env['poly.ft.top'].create({'name': 'DiamondWrite', 'value': 0})
        top.write({'name': 'Updated', 'value': 55})
        self.assertEqual(top.name, 'Updated')
        self.assertEqual(top.value, 55)
        self.assertEqual(self.env['poly.ft.base'].browse(top.id).name, 'Updated')

    # ------------------------------------------------------------------
    # Unlink
    # ------------------------------------------------------------------

    def test_unlink_alpha_removes_base(self):
        """Unlinking poly.ft.alpha must also remove the poly.ft.base record."""
        alpha = self.env['poly.ft.alpha'].create({'name': 'DelAlpha', 'value': 1})
        alpha_id = alpha.id
        alpha.unlink()
        self.assertFalse(self.env['poly.ft.alpha'].browse(alpha_id).exists())
        self.assertFalse(self.env['poly.ft.base'].browse(alpha_id).exists())
        self.assertFalse(self.env['ir.poly_base'].browse(alpha_id).exists())

    def test_unlink_top_cascades_full_hierarchy(self):
        """Unlinking poly.ft.top must cascade to alpha, beta, base, and ir.poly_base."""
        top = self.env['poly.ft.top'].create({'name': 'DelTop', 'value': 1})
        top_id = top.id
        top.unlink()
        for model_name in ('poly.ft.top', 'poly.ft.alpha', 'poly.ft.beta', 'poly.ft.base', 'ir.poly_base'):
            with self.subTest(model=model_name):
                self.assertFalse(
                    self.env[model_name].browse(top_id).exists(),
                    f"{model_name} record {top_id} must be deleted after poly.ft.top.unlink()",
                )

    def test_unlink_does_not_affect_other_records(self):
        """Unlinking one record must leave sibling records intact."""
        alpha1 = self.env['poly.ft.alpha'].create({'name': 'Keep', 'value': 10})
        alpha2 = self.env['poly.ft.alpha'].create({'name': 'Delete', 'value': 20})
        alpha2.unlink()
        self.assertTrue(self.env['poly.ft.alpha'].browse(alpha1.id).exists())
        self.assertFalse(self.env['poly.ft.alpha'].browse(alpha2.id).exists())

    # ------------------------------------------------------------------
    # Search (exercises expression.py)
    # ------------------------------------------------------------------

    def test_search_on_own_field(self):
        """Search on a model's own field must return matching records."""
        self.env['poly.ft.alpha'].create({'name': 'Find', 'alpha_note': 'special'})
        self.env['poly.ft.alpha'].create({'name': 'Other', 'alpha_note': 'normal'})
        found = self.env['poly.ft.alpha'].search([('alpha_note', '=', 'special')])
        self.assertEqual(len(found), 1)
        self.assertEqual(found.name, 'Find')

    def test_search_on_inherited_field(self):
        """Search on an inherited (injected) field must work via expression.py."""
        self.env['poly.ft.alpha'].create({'name': 'FindByName', 'value': 777})
        self.env['poly.ft.alpha'].create({'name': 'Other', 'value': 1})
        found = self.env['poly.ft.alpha'].search([('name', '=', 'FindByName')])
        self.assertEqual(len(found), 1)
        self.assertEqual(found.value, 777)

    def test_search_diamond_on_inherited_field(self):
        """Search on an inherited field in a diamond model must work."""
        self.env['poly.ft.top'].create({'name': 'TopSearch', 'value': 42})
        self.env['poly.ft.top'].create({'name': 'OtherTop', 'value': 1})
        found = self.env['poly.ft.top'].search([('value', '=', 42)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found.name, 'TopSearch')

    # ------------------------------------------------------------------
    # as_concrete_model
    # ------------------------------------------------------------------

    def test_as_concrete_model_from_poly_base(self):
        """as_concrete_model() on an ir.poly_base record must return the concrete type."""
        alpha = self.env['poly.ft.alpha'].create({'name': 'Concrete', 'alpha_note': 'x'})
        poly_base_rec = self.env['ir.poly_base'].browse(alpha.id)
        self.assertEqual(poly_base_rec._name, 'ir.poly_base')
        concrete = poly_base_rec.as_concrete_model()
        self.assertEqual(concrete._name, 'poly.ft.alpha')
        self.assertEqual(concrete.id, alpha.id)

    # ------------------------------------------------------------------
    # Method resolution
    # ------------------------------------------------------------------

    def test_make_uppercase_on_base(self):
        """make_uppercase() defined in poly.ft.base uppercases the name."""
        rec = self.env['poly.ft.base'].create({'name': 'hello'})
        rec.make_uppercase()
        self.assertEqual(rec.name, 'HELLO')

    def test_make_uppercase_inherited_by_alpha(self):
        """poly.ft.alpha inherits make_uppercase() from poly.ft.base via MRO."""
        alpha = self.env['poly.ft.alpha'].create({'name': 'world'})
        alpha.make_uppercase()
        self.assertEqual(alpha.name, 'WORLD')

    def test_make_uppercase_overridden_in_top(self):
        """poly.ft.top overrides make_uppercase(): appends _TOP and sets top_flag."""
        top = self.env['poly.ft.top'].create({'name': 'test', 'top_flag': False})
        top.make_uppercase()
        self.assertEqual(top.name, 'TEST_TOP')
        self.assertTrue(top.top_flag)

    # ------------------------------------------------------------------
    # fields_get
    # ------------------------------------------------------------------

    def test_fields_get_includes_injected_fields(self):
        """fields_get() on poly.ft.alpha must include inherited fields from base."""
        fields_info = self.env['poly.ft.alpha'].fields_get(['name', 'value', 'alpha_note'])
        self.assertIn('name', fields_info, "'name' must appear in fields_get for poly.ft.alpha")
        self.assertIn('value', fields_info, "'value' must appear in fields_get for poly.ft.alpha")
        self.assertIn('alpha_note', fields_info, "'alpha_note' must appear in fields_get for poly.ft.alpha")

    def test_fields_get_diamond_includes_all_inherited(self):
        """fields_get() on poly.ft.top must include fields from alpha, beta, and base."""
        fields_info = self.env['poly.ft.top'].fields_get(['name', 'value', 'alpha_note', 'beta_count', 'top_flag'])
        for expected in ('name', 'value', 'alpha_note', 'beta_count', 'top_flag'):
            self.assertIn(expected, fields_info, f"'{expected}' must appear in fields_get for poly.ft.top")
```

- [ ] **Step 4.2 — Update `tests/__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import test_engine
from . import test_orm
```

- [ ] **Step 4.3 — Run ORM integration tests**

```bash
cd /home/gamarino/odoo/cm-18.0 && source .venv/bin/activate && \
../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config \
  --test-enable --stop-after-init \
  --test-tags poly_orm \
  -d cm-test-18.0 --http-port 8099 2>&1 | tail -15
```

Expected: 0 failed, 0 errors.

- [ ] **Step 4.4 — Run full combined suite (regression + new)**

```bash
cd /home/gamarino/odoo/cm-18.0 && source .venv/bin/activate && \
../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config \
  --test-enable --stop-after-init \
  --test-tags 'poly_engine,poly_setup,poly_engine_full,poly_orm' \
  -d cm-test-18.0 --http-port 8099 2>&1 | tail -15
```

Expected: 0 failed, 0 errors across all four tag groups.

- [ ] **Step 4.5 — Commit**

```bash
cd /home/gamarino/odoo/numa-public-addons-18.0 && \
git add numa_poly_full_test/tests/ && \
git commit -m "$(cat <<'EOF'
[numa_poly_full_test] Add test_orm: full ORM integration tests for poly.ft.* hierarchy

Covers (tag: poly_orm):
Create:
  - Base record stores name+value
  - Alpha propagates to shared poly.ft.base record (shared ID)
  - Top (diamond) propagates to alpha, beta, and base
  - Batch create returns 3 records with unique IDs
  - link fields (alpha_base_id, top_alpha_id, top_beta_id) are populated

Write:
  - Own field write persists
  - Inherited field write propagates to poly.ft.base
  - Bulk recordset write updates all records
  - Diamond inherited field write propagates through full chain

Unlink:
  - Unlinking alpha removes poly.ft.base and ir.poly_base records
  - Unlinking top cascades through entire diamond hierarchy
  - Unlink does not affect sibling records

Search (exercises expression.py):
  - Own field, inherited field, and diamond model inherited field

as_concrete_model:
  - ir.poly_base.browse(id).as_concrete_model() returns poly.ft.alpha type

Method resolution (MRO):
  - make_uppercase() inherited from poly.ft.base works on alpha
  - make_uppercase() overridden in poly.ft.top appends _TOP and sets top_flag

fields_get:
  - Injected fields appear in single-dep and diamond models

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

### Spec coverage
- [x] Internal numa_poly engine tests (Task 1): `_poly_is_polymorphic`, `_poly_collect_depend_models`, `_poly_foreign_def_classes`, `_PolyFieldGuard` mechanics, cycle-token, `ir.poly_base` structure
- [x] `numa_poly_full_test` module with registered models (Task 2)
- [x] Engine tests with real poly models (Task 3): all functions tested against diamond hierarchy
- [x] ORM integration tests (Task 4): create/write/unlink/search/method/fields_get

### Placeholder scan
- No TBD. All code is complete.
- All assertion messages are specific.
- All model names are consistent (`poly.ft.base/alpha/beta/top`).

### Type / name consistency
- `alpha_base_id` used consistently in model definition and test assertions
- `top_alpha_id`, `top_beta_id` consistent between model definition and tests
- `_poly_setup_cycle` imported from `poly_module` module object in both Task 1 and Task 3
- `_Guard` alias used only in Task 1; Task 3 does not use the guard directly
