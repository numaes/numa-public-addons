## Polymorphic Implementation Strategy (Odoo 18)

The `numa_poly` implementation has converged on a clean, two-phase architecture that
works reliably with Odoo 18's incremental module loader and its `setup_models` cycle.

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

Field injection follows two independent mechanisms that must be kept in sync.

#### 3a. `_build_poly_fields` (primary, always-on)

Called from `PolyBase._setup_base` immediately *after* Odoo's standard
`_original_BaseModel._setup_base`. This ensures fields are injected in every
`setup_models` cycle, including test-framework registry resets.

**Algorithm:**

```
For each (base_model_name, link_field) in _depend_models:
    1. _poly_ensure_poly_ref(cls, base_model_name)   → inject PolyReference if missing
    2. For each field in base_model._fields:
        a. Skip technical fields (_POLY_TECHNICAL_FIELDS)
        b. Skip if already _poly_injected and not stored  ← tightened guard (see §3c)
        c. Resolve absolute origin via _poly_resolve_field_origin
        d. Copy field, set related='link.field_name', store=False
        e. _poly_inject_field(cls, fname, new_field)
```

`_poly_inject_field` does `setattr(cls, fname, field)` on the **registry class** (which
has `pool` set), so `Field.__set_name__` does NOT append the field to
`_field_definitions`. The injection therefore does not accumulate across restarts.

#### 3b. `_build_dependant_model_attributes` (legacy, retained for compatibility)

An older classmethod that copies fields and methods from dependency models. It is no
longer the primary injection path but is retained for edge cases (e.g., method
propagation and deep polymorphic hierarchies). It is a no-op for non-polymorphic models.

---

### 4. The Stale-Field Problem and its Fix

**Root cause:** `_poly_registry_setup_models` Phase 1 adds the *registry class* of
`numa.planning.node` (for example) to `project.task.__bases__`. The registry class has
`pool` set, so it is excluded from `_model_classes__`. However, its Python-level
definition class (`NumaPlanningNode`) is NOT excluded because it has no `pool` attribute.
Consequently, `_setup_base` sees `NumaPlanningNode._field_definitions` and adds
`pln_required_resource_ids` (and other dependency model fields) to `project.task._fields`
as **stored, non-related** entries, exactly as defined in the base model.

The previous `if fname in cls._fields: continue` guard in `_build_poly_fields` then
silently skipped those fields, leaving them as stored direct fields rather than related
proxies.

**Fix (commit `e7591ad`):** The guard is now tightened:

```python
if fname in cls._fields:
    existing = cls._fields[fname]
    if getattr(existing, '_poly_injected', False) and not getattr(existing, 'store', True):
        continue   # Already correctly injected — skip
    # Otherwise: stale stored field from parent _field_definitions — fall through to replace
```

A field is skipped **only** when it was previously injected by poly (`_poly_injected=True`
and `store=False`). Any other entry — including stale stored copies inherited from parent
`_field_definitions` via the MRO injection — is overwritten with the correct
related-via-link version.

---

### 5. `_poly_fields_built` Flag and Test Resets

`_build_poly_fields` sets `cls._poly_fields_built = True` after injection to guard
against redundant re-runs within the same `setup_models` cycle.

`_poly_registry_setup_models` clears this flag from every registry class *before* calling
`_original_Registry_setup_models`:

```python
for _cls in self.values():
    if isinstance(_cls, type) and '_poly_fields_built' in _cls.__dict__:
        delattr(_cls, '_poly_fields_built')
```

Without this clearing, the test framework's in-process registry reset
(`TestCase.doClassCleanups → registry.setup_models(cr)`) would trigger `_setup_base`
again for all models but `_build_poly_fields` would return early, leaving injected fields
absent for subsequent tests.

---

### 6. Registry Setup Phases Summary

| Phase | Location | Responsibility |
|-------|----------|---------------|
| 0 | `_poly_registry_setup_models` | Collect poly models; update `_depend_models` on registry class |
| 1 | `_poly_registry_setup_models` | Inject dependency registry classes into child `__bases__`; sync `__base_classes` |
| 2 | `_poly_registry_setup_models` | Clear `_poly_fields_built` on all registry classes |
| 3 | `_original_Registry_setup_models` | Standard Odoo `_prepare_setup` → `_setup_base` → `_setup_fields` |
| 3a | `PolyBase._setup_base` (inside phase 3) | Run `_build_poly_fields` to inject/replace related fields |
| 4 | `_poly_registry_setup_models` (post) | Clear `field_computed` cache |

---

### 7. Known Limitations and Design Notes

- **`poly_Field_setup_related` (deprecated):** An earlier patch on `Field.setup_related`
  that corrected related paths starting with model names (e.g. `'base.model.field'`) has
  been disabled. The stale-field replacement in `_build_poly_fields` makes it unnecessary.

- **Test model registration:** Models defined inside test files (e.g., `test_poly_setup.py`)
  are imported by `loader.make_suite()` *after* `registry.load()` completes. They are
  therefore never processed by `MetaModel`'s module-to-models registry and never appear in
  the ORM. Tests that rely on such models must call `skipTest` when the model is absent.

- **`_build_dependant_model_attributes` and `_field_definitions`:** The legacy path
  registers injected fields into `_field_definitions` via `__set_name__`. On the registry
  class this is a no-op (registry classes have `pool` set, so `is_definition_class` is
  False). If this method is ever called on a *definition* class, it could pollute
  `_field_definitions` and cause fields to be picked up as stored entries on the next
  `_setup_base`. The tightened guard in §4 handles this correctly regardless.

- **Many2many fields:** Poly-injected M2M fields must be `store=False, related=...`. The
  `_auto_init` hook enforces this as a safety net during module installation (`-u`), and
  `_build_poly_fields` enforces it at every `setup_models` run.
