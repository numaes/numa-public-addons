## Polymorphic Implementation Strategy (Odoo 18)

The `numa_poly` implementation has converged on a clean architecture that works reliably
with Odoo 18's incremental module loader and its `setup_models` cycle.

---

### 1. Strict Isolation and Detection

A model is considered polymorphic **exclusively** if its class hierarchy (MRO) contains
`_depend_models` with at least one non-empty entry.

- **Isolation:** Core Odoo models (`res.*`, `ir.*`, `base.*`, `mail.*`, etc.) are never
  modified. The poly engine only touches classes that explicitly declare `_depend_models`.
- **Key function:** `_poly_is_polymorphic(model)` performs this check safely and cheaply.

---

### 2. MRO Injection — `Model.__bases__`

**Problem (Odoo 18 constraint):** `AbstractModel` is an alias for `BaseModel` (the same
Python object). Replacing the module attribute `odoo.models.AbstractModel = PolyBase`
caused classes imported *before* this module to keep `_original_BaseModel` as their
direct base, while classes imported *after* received `PolyBase` directly. The resulting
mixed `__base_classes` entries broke Python's C3 linearisation for the `base` abstract
registry class when `setup_models` was called.

**Current approach:** Mutate `Model.__bases__` directly:

```python
if PolyBase not in odoo.models.Model.__bases__:
    odoo.models.Model.__bases__ = (PolyBase,)
```

This is idempotent (guarded by membership check) and consistent: every Odoo model class
— regardless of import order — carries `PolyBase` in its MRO through the stable
`Model → PolyBase → BaseModel` chain.
`TransientModel` gains `PolyBase` transitively via `TransientModel → Model`, so its
`__bases__` does not need an additional assignment.

In addition, `_poly_registry_setup_models` (Phase 1) injects each dependency model's
*registry class* into the polymorphic child's `__bases__` so the child can call its
methods. This injection must happen **before** `_original_Registry_setup_models` runs.

---

### 3. Field Injection Pipeline

Field injection is handled by a single entry point: `_build_poly_fields`, called from
`PolyBase._setup_base`. There is no secondary or legacy injection path.

#### `_PolyFieldGuard` — prevents stale-field bleeding

**Problem:** Phase-1 MRO injection adds the dependency model's registry class to
`project.task.__bases__`. The registry class inherits from its definition class
(e.g. `NumaPlanningNode`). Since `NumaPlanningNode.pool is None`, Odoo's `_setup_base`
would pick up `NumaPlanningNode._field_definitions` when scanning `_model_classes__`,
adding those fields as stored, non-related entries in the poly child's `_fields`.

**Fix:** `_PolyFieldGuard` is a context manager that:

1. Calls `_poly_foreign_def_classes(cls)` to identify all definition classes that
   appeared in `cls.__mro__` via Phase-1 injection (i.e., their `_name` is in
   `dep_map`), but are **not** part of `cls`'s own definition hierarchy.
2. Temporarily sets `_field_definitions = []` on each of those classes.
3. Restores the originals unconditionally on exit.

`PolyBase._setup_base` wraps `_original_BaseModel._setup_base` in this guard:

```python
def _setup_base(self):
    if _poly_is_polymorphic(type(self)):
        with _PolyFieldGuard(type(self)):
            _original_BaseModel._setup_base(self)
        type(self)._build_poly_fields(calling_self=self)
    else:
        _original_BaseModel._setup_base(self)
```

#### `_build_poly_fields` (sole injection entry point)

Called immediately after the guarded `_original_BaseModel._setup_base`. By this point
`cls._fields` contains only the model's own fields (no stale dep-model entries).

**Algorithm:**

```
For each (base_model_name, link_field) in _depend_models:
    1. _poly_ensure_poly_ref(cls, base_model_name)   → inject PolyReference if missing
    2. For each field in base_model._fields:
        a. Skip technical fields (_POLY_TECHNICAL_FIELDS)
        b. Skip if already _poly_injected   ← simple guard (no stale entries to replace)
        c. Resolve absolute origin via _poly_resolve_field_origin
        d. Copy field, set related='link.field_name', store=False, _poly_injected=True
        e. _poly_inject_field(cls, fname, new_field)
```

`_poly_inject_field` does `setattr(cls, fname, field)` on the **registry class** (which
has `pool` set), so `Field.__set_name__` does NOT append the field to `_field_definitions`.
The injection therefore does not accumulate across restarts.

---

### 4. `_poly_fields_built` Cycle Token

`_build_poly_fields` stores the current `_poly_setup_cycle` integer instead of a boolean:

```python
cls._poly_fields_built = _poly_setup_cycle   # cycle token, not True
```

The guard check:

```python
if getattr(cls, '_poly_fields_built', -1) == _poly_setup_cycle:
    return
```

`_poly_setup_cycle` is a module-level integer incremented once at the top of every
`_poly_registry_setup_models` call:

```python
global _poly_setup_cycle
_poly_setup_cycle += 1
```

**Benefit:** The stored token automatically becomes stale when a new `setup_models`
cycle begins. No explicit clearing loop is needed (the old Phase-2 loop that
`delattr`-ed `_poly_fields_built` from every registry class has been removed).

---

### 5. Registry Setup Phases Summary

| Phase | Location | Responsibility |
|-------|----------|---------------|
| 0 | `_poly_registry_setup_models` | Increment `_poly_setup_cycle`; collect poly models; update `_depend_models` on registry class |
| 1 | `_poly_registry_setup_models` | Inject dependency registry classes into child `__bases__`; sync `__base_classes` |
| 2 | `_original_Registry_setup_models` | Standard Odoo `_prepare_setup` → `_setup_base` → `_setup_fields` |
| 2a | `PolyBase._setup_base` (inside phase 2) | `_PolyFieldGuard` blanks foreign def class `_field_definitions`; `_build_poly_fields` injects related fields |
| 3 | `_poly_registry_setup_models` (post) | Clear `field_computed` cache |

---

### 6. Known Limitations and Design Notes

- **`poly_Field_setup_related` (deprecated):** An earlier patch on `Field.setup_related`
  that corrected related paths starting with model names (e.g. `'base.model.field'`) has
  been disabled. The `_PolyFieldGuard` makes it permanently unnecessary.

- **Test model registration:** Models defined inside test files (e.g., `test_poly_setup.py`)
  are imported by `loader.make_suite()` *after* `registry.load()` completes. They are
  therefore never processed by `MetaModel`'s module-to-models registry and never appear in
  the ORM. Tests that rely on such models must call `skipTest` when the model is absent.

- **Many2many fields:** Poly-injected M2M fields must be `store=False, related=...`. The
  `_auto_init` hook enforces this as a safety net during module installation (`-u`), and
  `_build_poly_fields` enforces it at every `setup_models` run.

- **Phase-1 and `super()` chains:** Keeping the dependency registry class in
  `project.task.__bases__` (rather than a method-copy proxy) ensures that dep model
  methods using `super()` continue to resolve correctly against their defining class.
  `_PolyFieldGuard` handles the `_field_definitions` side-effect without touching the MRO.
