# Poly Field Injection Redesign — Spec

**Date:** 2026-03-26
**Module:** `numa_poly`
**Status:** Approved

---

## Problem

`_build_dependant_model_attributes` (955 lines) contains three overlapping implementations of the
same field injection logic, builds `dep_map` three times (the second overwriting the first),
references loop variables (`name`, `field`, `related_base`) outside their loop scope causing
`UnboundLocalError`, and has ~300 lines of "field argument recovery" that exist solely to compensate
for injecting fields before `_setup_base` has run on the base model.

Root cause: Phase 1 in `_poly_registry_setup_models` attempts field injection before
`Registry.setup_models` calls `_setup_base`, so `base._fields` is not yet populated. All recovery
code patches that timing error.

---

## Core Invariant

`PolyReference('some.model')` returns `env['some.model'].browse(self.id)`. Because polymorphic
objects share IDs, no stored column is required. Every field inherited from a base is a
`related = (link_ref, field_name)` field where `link_ref` is the `PolyReference`.

---

## Separation of Responsibilities

| Moment | Responsibility |
|--------|---------------|
| Phase 1 (pre `_setup_models`) | MRO injection only (`__bases__` modification) |
| `_setup_base` override | Field injection via `_build_poly_fields` |

---

## New Module-Level Helpers

All pure functions; no side effects beyond the single field/class they operate on.

### `_poly_collect_depend_models(cls) -> OrderedDict`
Walk MRO; include only bases where `base.__dict__['_name'] == cls._name`; collect
`_depend_models` entries in definition order; no repetitions.

### `_poly_resolve_field_origin(fname, model, pool) -> (model_name, field_name)`
Follow the poly-related chain (a chain of `related=(PolyReference, fname)` fields) until
reaching the model that defines the field natively. Returns `(model_name, field_name)`.
Cycle-protected via `visited` set.

### `_poly_ensure_poly_ref(cls, target_model_name, dep_map) -> str`
Check whether a `PolyReference` to `target_model_name` already exists in `cls._fields`.
Prefer the name from `dep_map`; otherwise search existing PolyReferences; otherwise
generate `poly_<model_name_underscored>_id`. Create and inject if not found. Return link
field name.

### `_poly_inject_field(cls, fname, field) -> None`
Set `field` as class attribute on `cls`, add to `cls._fields`, propagate to the pool
proxy class if one exists and differs from `cls`.

---

## `_build_poly_fields` (replaces `_build_dependant_model_attributes`)

```
@classmethod
def _build_poly_fields(cls):
    1. Guard: return immediately for ir.poly_base, non-polymorphic, or already built.
    2. Set cls._poly_fields_built = True  (recursion guard).
    3. dep_map = _poly_collect_depend_models(cls)
    4. For each (base_model_name, link_field_name) in dep_map:
       a. _poly_ensure_poly_ref(cls, base_model_name, dep_map)
       b. base = cls.pool.get(base_model_name)
          → skip if None
       c. if not base._fields:
              base._setup_base()   # forces recursive _build_poly_fields if base is polymorphic
       d. for fname, field in base._fields.items():
              if fname in _TECHNICAL_FIELDS: continue
              if fname in cls._fields: continue
              if isinstance(field, PolyReference): continue
              origin_model, origin_fname = _poly_resolve_field_origin(fname, base, cls.pool)
              link = _poly_ensure_poly_ref(cls, origin_model, dep_map)
              new_field = copy.copy(field)
              new_field.related = f'{link}.{origin_fname}'
              new_field.store = False
              new_field.compute = None
              new_field.inverse = None
              new_field._setup_done = False
              _poly_inject_field(cls, fname, new_field)
    5. Inject infrastructure fields:
       - poly_base_id  → PolyReference('ir.poly_base')
       - create_uid    → related('poly_base_id.create_uid')
       - create_date   → related('poly_base_id.create_date')
       - write_uid     → related('poly_base_id.write_uid')
       - write_date    → related('poly_base_id.write_date')
```

Estimated size: ~150 lines.

---

## `_setup_base` Override (simplified)

```python
def _setup_base(self):
    _original_BaseModel._setup_base(self)
    if _poly_is_polymorphic(type(self)):
        type(self)._build_poly_fields()
```

Eliminates: 175-line method with three copies of `_odoo_core_prefixes` and a full pool scan.

---

## Phase 1 in `_poly_registry_setup_models` (MRO only)

```
collect poly_models_names_to_process
for model_name in poly_models_names_to_process:
    dep_map = _poly_collect_depend_models(model_class)
    parents = [registry[p] for p in dep_map if p in registry]
    if 'ir.poly_base' in registry:
        parents.append(registry['ir.poly_base'])
    inject_bases(model_class, deduplicated(parents))
call _original_Registry_setup_models(self, cr)
```

Remove all field injection calls from Phase 1.

---

## Eliminations

| What | Why |
|------|-----|
| `_setup_poly_fields` (112 lines) | Logic absorbed into `_build_poly_fields` + `_setup_base` |
| Field argument recovery (lines 2678–2957) | Copy.copy preserves all attributes |
| `add_subfields` nested function | Replaced by simple loop |
| `related_fields` dict + `field_subclass` dict | Replaced by `copy.copy` |
| Three `dep_map` builds | One via `_poly_collect_depend_models` |
| `related_counter` hack | `_poly_ensure_poly_ref` generates stable names |
| Aggressive takeover of `old_id`/`concrete_model_id` | Infrastructure fields injected cleanly |
| Pool-wide `referenced_as_base` scans | Not needed: only consumers inject fields |
| Duplicate `_odoo_core_prefixes` lists | One constant at module level |

---

## Technical Fields (skipped during injection)

```python
_POLY_TECHNICAL_FIELDS = frozenset({
    'id', '__last_update', 'display_name',
    'create_uid', 'create_date', 'write_uid', 'write_date',
})
```

Audit fields are re-injected explicitly pointing to `poly_base_id.*`.

---

## Testing

- Existing tests in `tests/test_poly_setup.py` and `tests/test_poly_improvements.py` must pass.
- Verify loading with `odoo-bin shell -c cm-18.0/odoo.config -d cm-test-18.0 --no-http`.
- No ERROR-level log lines from `numa_poly` during clean load.
