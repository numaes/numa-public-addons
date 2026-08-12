# Poly Field Injection Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 955-line `_build_dependant_model_attributes` and its satellite hacks with
a clean ~150-line `_build_poly_fields` backed by four pure helper functions, eliminating all
timing-induced field-argument recovery code.

**Architecture:** Field injection is deferred to `_setup_base` so `base._fields` is always
populated. Phase 1 of `_poly_registry_setup_models` is reduced to MRO-only injection.
`PolyReference` stays as-is; every inherited field becomes `related=(link, fname); store=False`.

**Tech Stack:** Python 3.12, Odoo 18 ORM, `copy.copy` for field cloning.

---

## File Map

| File | Change |
|------|--------|
| `numa_poly/models/poly.py` | All changes are in this file |

All modifications are within `poly.py`. No new files.

---

### Task 1: Add module-level constant and helper functions

Add four pure helper functions immediately after `_poly_is_polymorphic` (around line 179).
These replace ad-hoc logic scattered across the file.

**Files:**
- Modify: `numa_poly/models/poly.py` (after line ~179)

- [ ] **Step 1: Locate insertion point**

  Confirm line range of `_poly_is_polymorphic`:
  ```bash
  grep -n "_poly_is_polymorphic\|_poly_get_safe_mro\|_poly_processed_models" \
      numa_poly/models/poly.py | head -20
  ```

- [ ] **Step 2: Insert constant and four helper functions after `_poly_is_polymorphic`**

  Insert the following block immediately after the closing of `_poly_is_polymorphic`
  (after the `return False` at the end of that function):

  ```python
  # ---------------------------------------------------------------------------
  # Technical fields that are never inherited from a polymorphic base.
  # Audit fields (create_uid etc.) are re-injected explicitly via poly_base_id.
  # ---------------------------------------------------------------------------
  _POLY_TECHNICAL_FIELDS = frozenset({
      'id', '__last_update', 'display_name',
      'create_uid', 'create_date', 'write_uid', 'write_date',
      'old_id', 'concrete_model_id', 'poly_payload', 'poly_base_id',
  })


  def _poly_collect_depend_models(cls) -> 'OrderedDict':
      """
      Collect the consolidated _depend_models map for cls.

      Walk the MRO and include only bases where the base's own _name equals
      cls._name (i.e. mixin layers of the same model).  Entries are collected
      in definition order (subclass first) without repetition.

      Returns an OrderedDict {base_model_name: link_field_name}.
      """
      if getattr(cls, '_name', None) == 'ir.poly_base':
          return OrderedDict()
      result = OrderedDict()
      for base in _poly_get_safe_mro(cls):
          if getattr(base, '_name', None) != cls._name:
              continue
          dep = base.__dict__.get('_depend_models')
          if dep and isinstance(dep, (dict, OrderedDict)):
              for model_name, field_name in dep.items():
                  if model_name not in result:
                      result[model_name] = field_name
      return result


  def _poly_resolve_field_origin(fname: str, model, pool) -> 'tuple[str, str]':
      """
      Follow the polymorphic related chain to find the model that natively defines
      a field (i.e. where the field is NOT itself a poly-injected related).

      Returns (model_name, field_name).  If resolution fails, returns the
      input model name and fname unchanged.
      """
      visited: set = set()
      current_model_name: str = model._name
      current_fname: str = fname

      while True:
          key = (current_model_name, current_fname)
          if key in visited:
              break
          visited.add(key)

          current_model = pool.get(current_model_name)
          if current_model is None:
              break

          field = current_model._fields.get(current_fname)
          if field is None:
              break

          # A poly-injected related has the form related='link_field.field_name'
          # where link_field is a PolyReference.
          rel = getattr(field, 'related', None)
          if not rel:
              break  # native field — this is the origin

          # Normalise to string
          if isinstance(rel, (tuple, list)):
              rel = '.'.join(str(p) for p in rel)

          parts = rel.split('.', 1)
          if len(parts) != 2:
              break

          link_fname, sub_fname = parts
          link_field = current_model._fields.get(link_fname)
          if not isinstance(link_field, PolyReference):
              break  # not a poly bridge — stop

          current_model_name = link_field.comodel_name
          current_fname = sub_fname

      return current_model_name, current_fname


  def _poly_ensure_poly_ref(cls, target_model_name: str, dep_map: 'OrderedDict') -> str:
      """
      Ensure a PolyReference to *target_model_name* exists in cls._fields.

      Resolution order:
      1. Explicit name from dep_map (if target is a direct dependency).
      2. Existing PolyReference in cls._fields that already points to target.
      3. Auto-generated name: poly_<model_name_underscored>_id.

      Creates and injects the field if it does not yet exist.
      Returns the link field name.
      """
      # 1. Prefer the explicit link name declared in _depend_models
      explicit = dep_map.get(target_model_name)
      if explicit:
          if explicit not in cls._fields:
              _poly_inject_field(cls, explicit, PolyReference(target_model_name))
          return explicit

      # 2. Re-use an existing PolyReference to the same model
      for fname, field in list(cls._fields.items()):
          if isinstance(field, PolyReference) and field.comodel_name == target_model_name:
              return fname

      # 3. Generate a stable name
      auto_name = 'poly_{}_id'.format(target_model_name.replace('.', '_'))
      if auto_name not in cls._fields:
          _poly_inject_field(cls, auto_name, PolyReference(target_model_name))
      return auto_name


  def _poly_inject_field(cls, fname: str, field) -> None:
      """
      Inject *field* as *fname* into *cls*.

      Sets the field as a class attribute, registers it in cls._fields, and
      propagates it to the Odoo 18 pool proxy class when the proxy differs from cls.
      """
      setattr(cls, fname, field)
      cls._fields[fname] = field
      field.model_name = cls._name
      field.name = fname

      # Odoo 18 keeps a separate proxy class in pool.models; keep it in sync.
      try:
          pool = cls.pool  # type: ignore[attr-defined]
          proxy = pool.models.get(cls._name)
          if proxy is not None and proxy is not cls:
              setattr(proxy, fname, field)
              proxy._fields[fname] = field
      except Exception:
          pass
  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import sys; sys.path.insert(0, '..'); \
       import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```
  Expected: `syntax OK`

---

### Task 2: Add `_build_poly_fields` classmethod to `PolyBase`

This replaces `_build_dependant_model_attributes`. Place it immediately after the existing
`_build_dependant_model_attributes` definition ends (around line 3391) as a new classmethod.

**Files:**
- Modify: `numa_poly/models/poly.py`

- [ ] **Step 1: Locate end of `_build_dependant_model_attributes`**

  ```bash
  grep -n "_build_dependant_model_attributes\|def create\|def _prepare" \
      numa_poly/models/poly.py | head -15
  ```

- [ ] **Step 2: Insert `_build_poly_fields` after `_build_dependant_model_attributes`**

  Insert the following block immediately after the line
  `_logger.debug(f'_build_dependant_model_attributes finished')` (line ~3390),
  before the `@api.model_create_multi` decorator:

  ```python
      @classmethod
      def _build_poly_fields(cls) -> None:
          """
          Inject polymorphic fields into cls from its _depend_models chain.

          Called from _setup_base after the standard Odoo field setup so that
          base._fields is guaranteed to be populated.  Forces _setup_base on any
          base that has not yet been set up.

          Algorithm
          ---------
          1. Guard: skip ir.poly_base, non-polymorphic models, and models already built.
          2. Collect the consolidated dep_map via _poly_collect_depend_models.
          3. For each (base_model_name, link_field_name):
             a. Ensure the PolyReference link field exists in cls.
             b. Force _setup_base on the base if its _fields is empty.
             c. For every non-technical field in base._fields:
                - Resolve to its ultimate origin via _poly_resolve_field_origin.
                - Ensure a PolyReference to that origin exists in cls.
                - Inject a related=copy of the field.
          4. Inject infrastructure fields (poly_base_id and audit fields).
          """
          if cls._name == 'ir.poly_base':
              return
          if not _poly_is_polymorphic(cls):
              cls._poly_fields_built = True
              return
          if getattr(cls, '_poly_fields_built', False):
              return

          # Recursion guard — set before any recursive calls below.
          cls._poly_fields_built = True

          dep_map = _poly_collect_depend_models(cls)
          if not dep_map:
              return

          for base_model_name, link_field_name in dep_map.items():
              # Ensure the direct PolyReference bridge exists.
              _poly_ensure_poly_ref(cls, base_model_name, dep_map)

              base = cls.pool.get(base_model_name)
              if base is None:
                  _logger.warning(
                      '[poly] _build_poly_fields: base model %s not found for %s',
                      base_model_name, cls._name,
                  )
                  continue

              # Ensure the base has its fields populated.
              if not base._fields:
                  _logger.debug(
                      '[poly] _build_poly_fields: forcing _setup_base on %s for %s',
                      base_model_name, cls._name,
                  )
                  base._setup_base()

              for fname, field in list(base._fields.items()):
                  if fname in _POLY_TECHNICAL_FIELDS:
                      continue
                  if fname in cls._fields:
                      continue
                  if isinstance(field, PolyReference):
                      continue

                  origin_model, origin_fname = _poly_resolve_field_origin(
                      fname, base, cls.pool
                  )
                  link = _poly_ensure_poly_ref(cls, origin_model, dep_map)

                  new_field = copy.copy(field)
                  new_field.related = '{}.{}'.format(link, origin_fname)
                  new_field.store = False
                  new_field.compute = None
                  new_field.inverse = None
                  new_field._setup_done = False
                  try:
                      new_field._poly_injected = True
                  except Exception:
                      pass
                  _poly_inject_field(cls, fname, new_field)

          # --- Infrastructure fields ------------------------------------------
          # poly_base_id: direct bridge to ir.poly_base (shared ID).
          if 'poly_base_id' not in cls._fields:
              _poly_inject_field(
                  cls, 'poly_base_id',
                  PolyReference('ir.poly_base', string='Poly base', automatic=True, readonly=True),
              )

          # Audit fields relayed through poly_base_id.
          _audit = {
              'create_uid': fields.Many2one(
                  'res.users', string='Created by',
                  related='poly_base_id.create_uid', automatic=False,
              ),
              'create_date': fields.Datetime(
                  string='Created on',
                  related='poly_base_id.create_date', automatic=False,
              ),
              'write_uid': fields.Many2one(
                  'res.users', string='Last Updated by',
                  related='poly_base_id.write_uid', automatic=False,
              ),
              'write_date': fields.Datetime(
                  string='Last Updated on',
                  related='poly_base_id.write_date', automatic=False,
              ),
          }
          for fname, fobj in _audit.items():
              if fname not in cls._fields:
                  _poly_inject_field(cls, fname, fobj)

          _logger.debug('[poly] _build_poly_fields finished for %s', cls._name)
  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```

---

### Task 3: Simplify `_setup_base` to call `_build_poly_fields`

Replace the current 175-line `_setup_base` override with a minimal version that runs standard
Odoo setup first then calls `_build_poly_fields`.

**Files:**
- Modify: `numa_poly/models/poly.py` (lines ~1465–1639)

- [ ] **Step 1: Read current `_setup_base` to know exact line range**

  ```bash
  grep -n "def _setup_base\|def _setup_poly_fields\|def _check_migration" \
      numa_poly/models/poly.py | head -10
  ```

- [ ] **Step 2: Replace the body of `_setup_base`**

  Replace everything from `def _setup_base(self):` through the line before
  `def _setup_poly_fields(cls, self):` with:

  ```python
      def _setup_base(self):
          """Run standard Odoo field setup then inject polymorphic fields."""
          _original_BaseModel._setup_base(self)
          if _poly_is_polymorphic(type(self)):
              type(self)._build_poly_fields()
  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```

---

### Task 4: Remove `_setup_poly_fields`

`_setup_poly_fields` is now redundant — its only real work was calling
`_build_dependant_model_attributes`, which is superseded by `_build_poly_fields` called from
`_setup_base`.

**Files:**
- Modify: `numa_poly/models/poly.py` (lines ~1640–1751)

- [ ] **Step 1: Locate `_setup_poly_fields` boundaries**

  ```bash
  grep -n "def _setup_poly_fields\|def _check_migration" numa_poly/models/poly.py
  ```

- [ ] **Step 2: Delete the entire `_setup_poly_fields` method**

  Remove from `@classmethod` + `def _setup_poly_fields(cls, self):` through
  `except Exception as e:` + its body, up to (but not including)
  `def _check_migration_needed(self):`.

  Replace with a single deprecation stub that does nothing, so any lingering callers
  don't crash:

  ```python
      @classmethod
      def _setup_poly_fields(cls, self):
          """Deprecated: field injection is now handled in _setup_base via _build_poly_fields."""
          pass
  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```

---

### Task 5: Simplify Phase 1 in `_poly_registry_setup_models` — MRO only

Remove all calls to `_build_dependant_model_attributes` from Phase 1 and replace the body of
the model-processing loop with pure MRO injection using `_poly_collect_depend_models`.

**Files:**
- Modify: `numa_poly/models/poly.py` (lines ~5438–5618)

- [ ] **Step 1: Locate Phase 1 loop boundaries**

  ```bash
  grep -n "Phase 1\|Phase 2\|_original_Registry_setup_models\|_build_dependant_model" \
      numa_poly/models/poly.py | tail -30
  ```

- [ ] **Step 2: Replace Phase 1 loop body**

  Replace everything from the comment `# [poly] Phase 1: MRO Injection BEFORE Odoo's setup_models`
  through (but not including) `res = _original_Registry_setup_models(self, cr)` with:

  ```python
      # [poly] Phase 1: MRO Injection BEFORE Odoo's setup_models
      # Responsible ONLY for modifying __bases__ so that Odoo's own _setup_base sees
      # the correct inheritance hierarchy.  Field injection happens inside _setup_base.
      _logger.debug('[poly] Phase 1: MRO injection for %d models', len(poly_models_names_to_process))

      # Restore ir.poly_base integrity first.
      if 'ir.poly_base' in self:
          ir_poly_instance = self['ir.poly_base']
          if ir_poly_instance._fields:
              pass  # already set up; nothing to do
          # (standard _setup_base will run for ir.poly_base during setup_models)

      for model_name in poly_models_names_to_process:
          if model_name not in self:
              continue
          model_class = self[model_name]
          if not isinstance(model_class, type):
              continue

          try:
              dep_map = _poly_collect_depend_models(model_class)
              parents_cls = []
              for p_name in dep_map:
                  if p_name in self:
                      parents_cls.append(self[p_name])
              if 'ir.poly_base' in self and self['ir.poly_base'] not in parents_cls:
                  parents_cls.append(self['ir.poly_base'])

              if not parents_cls:
                  continue

              # Build deduplicated base list: poly parents first, then original non-poly bases.
              _bm_bases = getattr(model_class, '_BaseModel__base_classes', None)
              original_bases = list(
                  _bm_bases if _bm_bases
                  else [b for b in model_class.__bases__ if getattr(b, 'pool', None) is None]
              )
              new_bases = parents_cls + [b for b in original_bases if b not in parents_cls]

              # Deduplicate: drop a base if a more-derived class already covers it.
              deduplicated = []
              for b in new_bases:
                  if b is model_class:
                      continue
                  if any(b is not c and issubclass(c, b) for c in new_bases if c is not model_class):
                      continue
                  if b not in deduplicated:
                      deduplicated.append(b)
              final_bases = tuple(deduplicated)

              if final_bases and final_bases != tuple(model_class.__bases__):
                  _logger.debug(
                      '[poly] Phase 1: injecting MRO for %s: %s',
                      model_name,
                      [getattr(b, '_name', b.__name__) for b in final_bases],
                  )
                  model_class.__bases__ = final_bases
                  if hasattr(model_class, '_BaseModel__base_classes'):
                      model_class._BaseModel__base_classes = final_bases
                  if hasattr(ctypes.pythonapi, 'PyType_Modified'):
                      ctypes.pythonapi.PyType_Modified(ctypes.py_object(model_class))

          except Exception as e:
              _logger.error('[poly] Phase 1: MRO injection failed for %s: %s', model_name, e)

  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```

---

### Task 6: Simplify Phase 2 in `_poly_registry_setup_models`

Phase 2 was a "final MRO stabilization" that is now unnecessary because `_setup_base` handles
field injection correctly.  Replace with a minimal post-setup cache invalidation.

**Files:**
- Modify: `numa_poly/models/poly.py`

- [ ] **Step 1: Locate Phase 2 block**

  ```bash
  grep -n "Phase 2\|Modules loaded\|field_computed\|_blocked_prefixes\|Stabilizing" \
      numa_poly/models/poly.py | tail -30
  ```

- [ ] **Step 2: Replace Phase 2 body**

  Replace everything from `# [poly] Phase 2: Final MRO stabilization` through the end of
  `_poly_registry_setup_models` (the closing of the function) with:

  ```python
      # [poly] Phase 2: Post-setup cache invalidation.
      # _setup_base has already injected all polymorphic fields.
      # We only need to clear Odoo's computed-field caches for affected models.
      if 'field_computed' in self.__dict__:
          del self.__dict__['field_computed']

      _logger.debug('[poly] Registry setup complete')
      return res
  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```

---

### Task 7: Add `copy` import if missing and verify `_poly_fields_built` guard consistency

Ensure `import copy` is at the top and that references to `_poly_attributes_built` (old guard)
are updated to `_poly_fields_built` (new guard) so the two methods don't fight.

**Files:**
- Modify: `numa_poly/models/poly.py`

- [ ] **Step 1: Check if `import copy` already exists**

  ```bash
  grep -n "^import copy" numa_poly/models/poly.py
  ```

  If missing, add `import copy` after the existing stdlib imports (near the top).

- [ ] **Step 2: Ensure `_build_dependant_model_attributes` still references its own guard**

  `_build_dependant_model_attributes` checks `_poly_attributes_built`.
  `_build_poly_fields` checks `_poly_fields_built`.
  These are different flags — that is intentional.  `_build_dependant_model_attributes` is
  kept as-is (legacy, still reachable from old call sites) but `_build_poly_fields` is now
  the authoritative implementation.

  Verify no code path sets `_poly_fields_built` except `_build_poly_fields` itself:
  ```bash
  grep -n "_poly_fields_built" numa_poly/models/poly.py
  ```

- [ ] **Step 3: Verify syntax one final time**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```

---

### Task 8: Integration test — clean load

Run the existing shell test to confirm the module loads without ERROR-level log lines from
`numa_poly`.

**Files:**
- Read: `numa-public-addons-18.0/test_numa_poly_load.py` (existing test script)

- [ ] **Step 1: Run load test**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 \
      /home/gamarino/odoo/numa-public-odoo-18.0-numa/odoo-bin shell \
      -c /home/gamarino/odoo/cm-18.0/odoo.config \
      -d cm-test-18.0 \
      --no-http \
      < /home/gamarino/odoo/numa-public-addons-18.0/test_numa_poly_load.py 2>&1
  ```

  Expected:
  - `RESULT: SUCCESS — All tests passed`
  - No `ERROR` lines from `odoo.addons.numa_poly`
  - No `UnboundLocalError` or `Phase 1: Failed`

- [ ] **Step 2: Check for unexpected ERRORs in the full log**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 \
      /home/gamarino/odoo/numa-public-odoo-18.0-numa/odoo-bin shell \
      -c /home/gamarino/odoo/cm-18.0/odoo.config \
      -d cm-test-18.0 \
      --no-http \
      < /dev/null 2>&1 | grep "ERROR.*numa_poly"
  ```

  Expected: empty output (zero ERROR lines from numa_poly).

---

### Task 9: Revert the temporary traceback-logging change

In Task 0 (pre-plan) we added `traceback.format_exc()` to the Phase 1 error handler for
diagnosis. Now that Phase 1 no longer has that error path, revert the change.

**Files:**
- Modify: `numa_poly/models/poly.py`

- [ ] **Step 1: Check if the temporary change is still present**

  ```bash
  grep -n "format_exc\|import traceback" numa_poly/models/poly.py
  ```

- [ ] **Step 2: Remove if found**

  If the line `import traceback as _tb` and `_tb.format_exc()` are still present, remove them.
  The Phase 1 error handler should be:
  ```python
  except Exception as e:
      _logger.error('[poly] Phase 1: MRO injection failed for %s: %s', model_name, e)
  ```

- [ ] **Step 3: Final syntax check**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  /home/gamarino/odoo/cm-18.0/.venv/bin/python3 -c \
      "import ast, pathlib; \
       src = pathlib.Path('../numa-public-addons-18.0/numa_poly/models/poly.py').read_text(); \
       ast.parse(src); print('syntax OK')"
  ```

---

### Task 10: Commit

- [ ] **Step 1: Stage and commit**

  ```bash
  cd /home/gamarino/odoo/numa-public-addons-18.0 && \
  git add numa_poly/models/poly.py docs/superpowers/ && \
  git commit -m "$(cat <<'EOF'
  refactor(numa_poly): clean redesign of polymorphic field injection

  Replace the 955-line _build_dependant_model_attributes (three overlapping
  implementations, duplicated dep_map construction, out-of-scope variable
  references causing UnboundLocalError, 300 lines of timing-induced field
  argument recovery) with a clean _build_poly_fields (~150 lines) backed by
  four pure module-level helpers.

  Key changes:
  - _poly_collect_depend_models: single MRO walk, same-_name bases only
  - _poly_resolve_field_origin: follows poly-related chain to concrete origin
  - _poly_ensure_poly_ref: idempotent PolyReference creation
  - _poly_inject_field: injects into cls, _fields, and pool proxy
  - _build_poly_fields: called from _setup_base; forces base._setup_base()
    when base._fields is empty, eliminating all field-argument recovery hacks
  - _setup_base reduced to 3 lines
  - _setup_poly_fields stubbed out (deprecated)
  - Phase 1 of _poly_registry_setup_models: MRO injection only, no fields
  - Phase 2 reduced to cache invalidation

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  )"
  ```
