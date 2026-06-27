# numa_poly — Upgrade & compatibility notes

> **Odoo version: 18.0 ONLY.** numa_poly implements polymorphic inheritance by
> monkey-patching Odoo ORM/registry internals. These internals change between major
> Odoo releases, so the module is pinned to Odoo **18.0** (`version` `18.0.x.y.z`).
> Do **not** load it on another major version without re-validating every patch below
> and running the full test suite. Treat any Odoo minor upgrade as requiring a smoke
> run of `numa_poly`, `numa_planning` and the bridges.

## Why this matters

numa_poly is a **core dependency of the whole Numa suite** (numa_planning and its
project/MRP/purchase bridges, numa_ai, etc.). A regression here affects every
dependent module. Changes to `models/poly.py` must keep the test suites green:

```bash
odoo-bin -d <db> -u numa_poly        --test-enable --test-tags '/numa_poly'
odoo-bin -d <db> -u numa_planning    --test-enable --test-tags '/numa_planning'
odoo-bin -d <db> -u numa_planning_project,numa_planning_mrp,numa_planning_purchase \
                                     --test-enable --test-tags '/numa_planning_project,/numa_planning_mrp,/numa_planning_purchase'
```

## Inventory of Odoo internals patched (models/poly.py)

Each of these wraps or replaces an Odoo core symbol; verify it against the target
Odoo version's source before upgrading.

| Patched symbol | numa_poly replacement | Purpose |
|----------------|-----------------------|---------|
| `models.Model.__bases__` | `(PolyBase,)` | Inject PolyBase so every model gains poly behaviour |
| `models.BaseModel._inherits_check` | `poly_inherits_check` | Repair comodel/ondelete on inherited fields |
| `models.BaseModel._add_field` | `poly_BaseModel_add_field` | Force base fields to related (no-shadow aware) |
| `models.BaseModel._fetch_query` | `poly_BaseModel_fetch_query` | Tolerate not-yet-created columns during boot |
| `models.BaseModel.__repr__` | `poly_BaseModel_repr` | Cheap repr without triggering `__getattribute__` |
| `fields.Field.__get__` / `__set__` | `_poly_Field_get` / `_poly_Field_set` | Polymorphic field access |
| `fields._Relational.__get__` | `_poly_Relational_get` | Polymorphic relational access |
| `fields.One2many.__get__` | `_poly_One2many_get` | Polymorphic o2m access |
| `fields.Field.setup` | `poly_Field_setup` | Recover/redirect field metadata (no-shadow aware) |
| `fields.Field.resolve_depends` / `get_depends` | `poly_Field_resolve_depends` / `poly_Field_get_depends` | Dependency resolution for poly fields |
| `fields.Many2one.convert_to_read` | `poly_many2one_convert_to_read` | PolyReference read conversion |
| `fields.Many2many.setup_nonrelated` | `poly_many2many_setup_nonrelated` | PolyReference m2m setup |
| `modules.registry.Registry.setup_models` | `_poly_registry_setup_models` | Central MRO injection + cache reset |
| `modules.registry.Registry.init_models` | `_poly_registry_init_models` | Poly-aware model init |
| `modules.registry.Registry.load` / `new` | `_poly_registry_load` / `_poly_registry_new` | Registry lifecycle hooks |

## Design invariants to preserve (regression-prone)

- **No-shadow rule:** a concrete model that becomes polymorphic keeps its OWN fields;
  only base-only fields are injected as related (`_poly_native_field_names`,
  `_poly_leaf_columns`). Breaking this re-introduces the res.partner/project.task
  `MissingError` and Text-vs-Char registry crashes. (Tests: bridge suites.)
- **Field-state restoration:** `create()` flips `store`/`related`/`inherited` on shared
  Field objects and restores them in a `try/finally`. The finally must always run.
  (Test: `test_10_create_failure_restores_field_state`.)
- **Schema caches** (`_POLY_LEAF_COLUMNS`, `_POLY_COLUMN_CACHE`) are cleared on every
  registry rebuild; do not cache schema across generations.

## Known open issue (tracked)

Creating a new `res.company` in a database with `stock` installed fails
(`stock.warehouse._check_company` under the poly `create`). Multi-company tests in
numa_planning self-skip where a second company cannot be created. Investigate as part
of further numa_poly hardening.
