# numa_poly on Odoo 20.0 — redesign specification

Written 2026-09-20, after auditing every patch point listed in `UPGRADE.md`
against the Odoo 20.0 source at `numa-public-odoo-20.0-numa`.

**This is not a port.** The three techniques numa_poly is built on stopped
being legal, and each of them is now actively defended against by the
framework. What follows is what replaces them, and why the replacement is
smaller than what it replaces.

Every claim below cites the Odoo 20.0 file and line that justifies it. Verify
before changing any of it.

## 1. What stopped working, and why

### 1.1 Rebasing a model class is undone, then asserted against

`odoo/orm/model_classes.py:353-360`:

```python
def _prepare_setup(model_cls):
    if model_cls._setup_done__:
        assert model_cls.__bases__ == model_cls._base_classes__
        return
    if model_cls.__bases__ != model_cls._base_classes__:
        model_cls.__bases__ = model_cls._base_classes__
```

`_poly_registry_setup_models` injects base classes into each model's MRO after
the registry has built it, and `_poly_sync_proxy_class` (poly.py:2317) rebases
the pool's class on top. Odoo 20 restores `__bases__` from `_base_classes__` on
the next setup pass and asserts nobody touched it on the one after.

### 1.2 A field that no Python class declares cannot be added

`odoo/orm/model_classes.py:632-639` raises `ValidationError` unless the name is
declared as a `Field` on the model class or one of its `_inherits` parents, or
starts with `x_`. numa_poly's whole strategy is injecting base-only fields onto
concrete models (`poly_BaseModel_add_field`, `_poly_inject_field` poly.py:636).

Compounding it, `model_cls._fields` is a read-only `MappingProxyType` over
`_fields__` (`model_classes.py:204`), and poly writes to it directly in several
places (poly.py:646, `poly_inherits_check` poly.py:341).

### 1.3 Field objects are shared between databases

`odoo/orm/model_classes.py:34` keeps `SHARED_FIELD_CACHE`, a process-wide
`WeakValueDictionary` keyed by `(model_name, base_fields)`. One `Field`
instance serves every registry that computed the same key, which means every
database served by the same worker.

numa_poly's two central techniques mutate `Field` objects in place:
`_poly_force_related`, and `create()` flipping `store`/`related`/`inherited`
with a `try/finally` restore — the invariant `UPGRADE.md` calls out as
regression-prone. In Odoo 20 that corrupts other databases.

And it would not even survive: `odoo/orm/registry.py:527-537` does
`field.__dict__.clear(); field.__init__(_base_fields__=base_fields)` on every
incremental setup, wiping any mutation mid-load.

### 1.4 The domain engine cannot be replaced

`odoo/osv/` is gone. `expression.py:890` assigns
`osv.expression.expression = PolyExpression`; there is no equivalent
indirection. `BaseModel._search` (`odoo/orm/models.py:4887-4903`) calls
`Domain(domain).optimize_full(self)` and `domain._to_sql(query.table)`
directly, dispatching to concrete `Domain` subclasses by reference
(`odoo/orm/domains.py:222, 256-262`).

## 2. The architecture that replaces it

Odoo 20 formalises a distinction Odoo 18 only implied
(`model_classes.py:36-70`): **model definitions** are the static classes in
module source; **model classes** are built by the registry, inheriting from all
the definitions of the model *and from the model classes of the models it
inherits*.

That last clause is the seam numa_poly needs. It does not have to inject
anything: it has to **declare**, and let the registry compute `_base_classes__`
itself.

### 2.1 Declare instead of inject

A polymorphic concrete model must inherit its base through the framework's own
`_inherit`, so that:

- `_base_classes__` comes out containing the base's model class, computed by
  Odoo, so §1.1's assert holds by construction;
- every base field is declared on a Python class in the MRO, so §1.2's guard
  passes by construction.

`Model.__bases__ = (PolyBase,)` at import time stays legal and is still how
every model gains the poly API: it happens before any registry is built, so it
flows into the model definitions naturally. What goes is the *per-model,
post-setup* re-injection and the proxy-class rebasing.

**Open question for implementation:** how a concrete model declares its poly
base. Either the module rewrites `_inherit` on the model definitions before the
registry reads them, or polymorphic models declare it themselves. The first
keeps today's transparency, the second is honest Odoo. Decide with a spike
before writing the phase.

### 2.2 Own the fields instead of mutating shared ones

`add_field(model_cls, name, field, shareable=False)`
(`model_classes.py:628`) takes a `shareable` flag precisely to opt a field out
of the shared cache. Every field numa_poly creates or alters must be its own
instance, added with `shareable=False`, and never mutated after setup.

The `create()` dance that flips `store`/`related`/`inherited` on live fields
has to go. What it achieves — writing a base field through a concrete record —
belongs in the field class, not in a global flag flip.

### 2.3 The polymorphism moves into the field class

`expression.py` is 890 lines. Around **15** of them are polymorphism
(lines 467-495, 509-516, 547-552), and all three say the same thing: *for a
`PolyReference`, the join key is `id`, not a foreign key column*. The rest is a
verbatim fork of Odoo 18's `expression.parse()` plus scaffolding that hides
registry-boot fragility.

Odoo 20 gives that idea a first-class home:

- `Field.join(table, kind)` (`odoo/orm/fields_relational.py:550`) builds the
  join as `SQL("%s = %s", table[self.name], coalias.id)`. Override it to join
  on `table.id` and the poly delta is expressed once, correctly.
- `compute_sql` (`odoo/orm/fields.py:251, 299`, applied in `to_sql` at
  `:1365-1371`) is the sanctioned way to give a non-stored field an SQL
  expression. `domains.py:1021` rejects a non-stored field without it, so this
  is required, not optional.
- With those two, `Many2one.condition_to_sql`
  (`fields_relational.py:484-544`) generates both the join and the subselect
  forms, `Many2one.property_to_sql` (`:477`) makes dotted paths work, and
  `_compute_sql_related` (`fields.py:776`) covers the third delta for free.

**`expression.py` is deleted.** It is replaced by roughly thirty lines on
`PolyReference`.

The scaffolding must not be ported. It injects fake `Id` fields and swallows
`Exception` to survive an incomplete `_fields` during registry build. Odoo 20
is stricter, not looser — `DomainCondition.__get_field` (`domains.py:963`),
`TableSQL.__getitem__` (`query.py:324`) and `_order_field_to_sql`
(`models.py:4791`) all raise on an unknown field. If poly still needs those
hacks, the bug is in its registry manipulation and belongs fixed there.

### 2.4 A new anchor for post-load stabilization

`Registry.signal_changes` is gone. `_signal_changes(cr, names)`
(`registry.py:1124`) is a different thing: it fires per transaction, from
`odoo/orm/environments.py:976`, with a set of cache names. `Registry.new` now
ends with `registry.ready = True` (`registry.py:264-267`) and offers no hook.
`registry._init`, `registry.registry_invalidated` and
`registry.cache_invalidated`, which `_poly_stabilize_registry`
(poly.py:7350-7377) reads and restores, do not exist.

If §2.1 works, most of what stabilization does stops being necessary, because
there is no MRO to re-inject. Whatever remains needs a new anchor; the
realistic candidate is `odoo.modules.loading.load_modules`. Note poly's
existing `load_module_graph` wrapper no longer matches either: Odoo 20's
signature is `(env, graph, update_module=False, report=None, install_demo=True)`
(`odoo/modules/loading.py:114-120`).

## 3. Straight renames

These need no thought, only care:

| Today | Odoo 20.0 |
| --- | --- |
| `odoo.models.INSERT_BATCH_SIZE`, `UPDATE_BATCH_SIZE` | `odoo.orm.models` (not re-exported) |
| `odoo.models.GC_UNLINK_LIMIT` | `odoo.tools.constants` |
| `odoo.tools.Query` | `odoo.orm.query.Query`, and the constructor is now `Query(model, alias=None, table=None)` |
| `odoo.api.Self` | `typing.Self` |
| `odoo.fields._Relational` | `odoo.orm.fields_relational._Relational` |
| `field._setup_attrs` | `field._setup_attrs__` |
| `BaseModel._inherits_check` | module-level `_check_inherits(model_cls)`, validate-only |
| `BaseModel._add_field` | module-level `add_field(model_cls, name, field, shareable)` |
| `BaseModel._pop_field` | module-level `pop_field(model_cls, name)` |
| `Registry.setup_models` | `Registry._setup_models__(cr, model_names=None)`, decorated `@locked` |
| `Registry.load(cr, module)` | `Registry.load(module: ModuleNode)` |
| `registry._init` | `registry.loaded` |
| `expression.NEGATIVE_TERM_OPERATORS` | `Domain.NEGATIVE_OPERATORS` |
| `expression.OR` / `AND` | `Domain.OR` / `Domain.AND` |
| `BaseModel._order_field_to_sql` | `(table: TableSQL, field_expr, direction, nulls)` |

`BaseModel.__repr__`: upstream is already the cheap form
(`odoo/orm/models.py:6165`). Delete the patch.

`Field.setup_full` / `setup_base`: gone from the tree. poly.py:880 calls
`setup_full` in a recovery path that can now never fire. Delete it.

`field.auto_join`: **absent from the entire Odoo 20 Python source.**
`PolyReference.auto_join = True` (poly.py:1729) is a dead attribute. The
concept is now `bypass_search_access`
(`odoo/orm/fields_relational.py:38`), which drives the join-versus-subselect
choice in `Many2one.condition_to_sql:492-509`.

`PolyReference._search_related` (poly.py:1839) starts with
`assert operator not in ('any', 'not any')`. In Odoo 20 search methods *are*
called with those operators (`domains.py:1052, 1070`), with the value already
converted to a `Query` (`:1064-1065`). That assertion fires on the first
relational search.

## 4. The JavaScript is dead, and was dead in 18.0 too

- `PolyListRenderer.setup()` calls `useService("rpc")`. No `rpc` **service** is
  registered in Odoo 18 or 20 — nothing in either core registers or uses one,
  and `useService` raises `Service rpc is not available`
  (`addons/web/static/src/core/utils/hooks.js:157-161`). The component throws
  on mount. The API is `import { rpc } from "@web/core/network/rpc"`.
- `super.onOpenRecord(record)`: `onOpenRecord` does not exist anywhere in
  `addons/web/static/src` in either version.
- `super.onAdd(ev)`: in Odoo 20 `onAdd` is a prop
  (`list_renderer.js:137`, called at `:466`), not a method.
- `onCellClicked(column, record)`: the real signature is
  `(record, column, ev, newWindow)` (`list_renderer.js:1520`); in 18.0 it was
  `(record, column, ev)`. The arguments have always been the wrong way round.

Nothing loads it: `views/poly_views.xml`, the only file referencing
`numa_polimorphic_widget`, is **not in the manifest's `data`**.

Decide deliberately: rewrite it against `props.openRecord`
(`list_renderer.js:136, 1570`) and the `rpc` function, or delete it. Do not
port it as it stands.

## 5. Security

`security/ir.model.access.csv` has `access_poly_base` with **no group**. In
`ir.access` a row without a group is a *restriction* applied to everyone, not a
permission. Converting it literally makes `ir.poly_base` inaccessible to all.

## 6. Order of work

The 17 test files (~2,500 lines) are the specification of what must stay true.
They are the asset that makes this possible; do not weaken them to make a phase
pass.

1. **Import.** Straight renames from §3, delete `expression.py` and the dead
   patches. Goal: `import` succeeds. No behaviour yet.
2. **Spike §2.1.** Can a concrete model declare its poly base through
   `_inherit` and come out with the fields it needs? This decides everything
   after it; answer it with throwaway code before writing phase 3.
3. **Declare instead of inject.** Replace the MRO injection and
   `_poly_inject_field` with the result of the spike. Retire
   `_poly_sync_proxy_class`.
4. **Own the fields.** `shareable=False` everywhere, remove the `create()`
   flag-flipping, move what it achieved into the field class.
5. **`PolyReference` as a real field.** `join()`, `compute_sql`, `search` for
   the new operator set. Delete the `auto_join` and `any` assertions.
6. **Stabilization anchor**, if anything still needs one after step 3.
7. **Security, data, manifest**, and the JS decision from §4.
8. `numa_poly_test` (another ~1,500 lines), then the four dependants:
   `numa_big_id`, `numa_fsm`, `numa_fsm_crm`, `numa_fsm_hr`.

Each phase ends with the suite run and the result recorded. A phase that needs
a test changed is a phase that needs a conversation first.
