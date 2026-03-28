## Lessons Learned: numa_poly Integration with Odoo 18

### 1. AbstractModel IS BaseModel — Module-Alias Replacement Breaks C3

In Odoo 18, `AbstractModel` is simply an alias for `BaseModel` (the same Python object).
Replacing the module attribute with `odoo.models.AbstractModel = PolyBase` caused classes
imported *before* that statement to keep `_original_BaseModel` as their direct Python base,
while classes imported *after* received `PolyBase` directly. The resulting mixed
`__base_classes` sets in the registry broke Python's C3 linearisation for the `base`
abstract class when `setup_models` was called, producing:

```
TypeError: Cannot create a consistent method resolution order (MRO) for bases PolyBase, base
```

**Fix:** Mutate `Model.__bases__` instead:

```python
if PolyBase not in odoo.models.Model.__bases__:
    odoo.models.Model.__bases__ = (PolyBase,)
```

`TransientModel` gains `PolyBase` transitively — no additional `__bases__` assignment
needed. `odoo.models.BaseModel = PolyBase` is kept only as a backward-compatibility alias
for `isinstance` checks.

---

### 2. MRO Injection Bleeds Parent `_field_definitions` into Child

When `_poly_registry_setup_models` Phase 1 adds a dependency model's *registry class* to
the child's `__bases__`, the Python MRO also includes all *definition classes* of the
dependency model (those without `pool`). Odoo's `_setup_base` uses:

```python
cls._model_classes__ = tuple(c for c in cls.mro() if getattr(c, 'pool', None) is None)
```

Those definition classes carry `_field_definitions` with the original field definitions
(e.g., `pln_required_resource_ids` as a stored `Many2many`). `_setup_base` picks them up
and adds them to the child's `_fields` as stored, non-related entries.

The previous guard `if fname in cls._fields: continue` in `_build_poly_fields` then
silently skipped those fields, leaving them as stored direct fields instead of related
proxies. The result was test failures:

```
AssertionError: None is not true : M2M field from depend_model MUST be related
```

**Fix:** Tighten the skip guard to only skip fields already correctly injected by poly:

```python
if getattr(existing, '_poly_injected', False) and not getattr(existing, 'store', True):
    continue  # Already correct — skip
# Otherwise: stale entry — fall through to replace
```

---

### 3. `_poly_fields_built` Must Be Cleared Before Every `setup_models`

`_build_poly_fields` sets `cls._poly_fields_built = True` as a within-cycle recursion
guard. Without clearing it at the start of each `setup_models` call, the test framework's
in-process registry reset triggers `_setup_base` again but `_build_poly_fields` returns
early, leaving polymorphic fields absent for subsequent tests.

**Fix:** Iterate over all registry classes and `delattr(_poly_fields_built)` at the
beginning of `_poly_registry_setup_models`, before calling
`_original_Registry_setup_models`.

---

### 4. Persistent Many2many Fields — Must Be `store=False` and `related`

Polymorphic Many2many fields must be `store=False, related='link_field.m2m_field'` on
child models. Odoo will otherwise attempt to create a physical relation table using the
parent's table name, resulting in SQL errors (duplicate relation, FK to wrong table).

The `_auto_init` hook in `PolyBase` enforces this as a last-resort safeguard during
module installation (`-u`). `_build_poly_fields` enforces it at every `setup_models` run
by replacing stale stored entries with the correct related version.

---

### 5. Test Models in Test Files Are Never Registered

Models defined inside test files (e.g., `class PolyChildModel(models.Model)` in
`test_poly_setup.py`) are imported by `loader.make_suite()` *after* `registry.load()` has
already completed. `MetaModel` records them in `module_to_models` but they never reach
`_build_model`, so they are absent from the registry.

Tests that require such models must call `self.skipTest(...)` when the model is absent,
rather than failing with a `KeyError`:

```python
if 'test.poly.child' not in self.env:
    self.skipTest("test.poly.child not in registry — ...")
```

---

### 6. `Field.__set_name__` Populates `_field_definitions` on Definition Classes

When `setattr(cls, name, field)` is called on a *definition* class (one without `pool`),
Python's descriptor protocol triggers `field.__set_name__(cls, name)`, which appends the
field to `cls._field_definitions`. On subsequent `_setup_base` calls, that field will be
picked up as if it were natively defined on the class — with its original attributes
(e.g., `related=None`, `store=True`).

This is why `_poly_inject_field` targets the **registry class** (which has `pool` set):
`is_definition_class(registry_class)` is `False`, so `__set_name__` does not append to
`_field_definitions`. Always inject onto the registry class, not a definition class.

---

### 7. Aggressive Odoo 18 Field Introspection

Odoo 18 clones field attributes (especially `related`) based on the class MRO during
`_setup_base`. If a class inherits from a polymorphic base, Odoo can inject `related`
paths pointing to the base model name (e.g., `related='base.model.field'`) rather than to
the link field. The `poly_Field_setup_related` patch was an early workaround for this; it
has been superseded by the stale-field replacement approach in `_build_poly_fields`.

---

### 8. Importance of Post-Install Configuration Tests

`post_install` tests run against the fully-loaded registry (without a separate `-u` pass)
and verify that `setup_models` leaves fields in the correct state. They are the most
reliable way to catch polymorphic initialisation issues that are invisible during normal
operation but fail during `update all` or a fresh install.

The `TestPolySetup` class (`numa_poly/tests/test_poly_setup.py`) covers:

- `test_m2m_polymorphic_read` — verifies that M2M fields from dependency models are
  related and non-stored on the polymorphic child.
- `test_stale_stored_field_removal` — verifies that `_build_poly_fields` replaces stale
  stored entries injected by `_setup_base` via the MRO-bleed described in lesson 2.
- `test_related_path_correction` — skipped (feature deprecated); documents the skip
  reason for future reference.
