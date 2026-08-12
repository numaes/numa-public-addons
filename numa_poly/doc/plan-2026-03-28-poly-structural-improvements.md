# numa_poly Structural Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first three architectural improvements identified in the module evaluation: (1) eliminate the stale-field root cause via a `_PolyFieldGuard` context manager, (2) remove the ~960-line dead-code function `_build_dependant_model_attributes`, and (3) consolidate field injection to the single `_build_poly_fields` route.

**Architecture:** Tasks 1–3 are sequential; Task 1 changes `_setup_base` and simplifies the skip guard in `_build_poly_fields`; Task 2 deletes the legacy function entirely; Task 3 cleans up the now-single injection path with documentation and the cycle-token improvement for `_poly_fields_built`. Each task ends with a passing test run.

**Tech Stack:** Python 3.10, Odoo 18, `odoo.models.MetaModel`, `odoo.fields`, `ctypes`

---

## File Map

| File | Role |
|---|---|
| `numa_poly/models/poly.py` | All implementation changes |
| `numa_poly/tests/test_poly_setup.py` | Existing integration tests (must stay green) |
| `numa_poly/tests/test_poly_improvements.py` | Existing unit tests (must stay green) |

---

## Task 1 — Structural fix: `_PolyFieldGuard` eliminates stale-field root cause

**Problem:** Phase-1 MRO injection adds `self['numa.planning.node']` (a registry class) to
`project.task.__bases__`. Because that registry class inherits from `NumaPlanningNode`
(a definition class with `pool is None`), `_setup_base` picks up
`NumaPlanningNode._field_definitions` when scanning `_model_classes__` for `project.task`.
This creates stale stored entries (e.g. `pln_required_resource_ids` with `store=True`) that
`_build_poly_fields` must overwrite.

**Fix:** Wrap the `_original_BaseModel._setup_base(self)` call (inside `PolyBase._setup_base`)
in a context manager that temporarily sets `_field_definitions = []` on all definition classes
that are "foreign" to the current poly model (i.e., that come from a dep model's ancestry
rather than the current model's own class hierarchy). After the call, the manager restores the
original lists. No stale entries are created; the replacement logic in `_build_poly_fields`
becomes unnecessary and its skip guard simplifies back to `if _poly_injected: continue`.

**Files:**
- Modify: `numa_poly/models/poly.py` (functions: `PolyBase._setup_base`, `PolyBase._build_poly_fields`, new helper `_poly_foreign_def_classes`, new context manager `_PolyFieldGuard`)

- [ ] **Step 1.1 — Write the failing assertion**

  Add a test at the bottom of `numa_poly/tests/test_poly_setup.py` that directly asserts
  no stale stored entry is created by `_setup_base` (before `_build_poly_fields` replaces it):

  ```python
  def test_no_stale_stored_entry_before_poly_injection(self):
      """
      _setup_base must never create a stored entry for fields that belong
      to a dep model's definition classes.  The guard prevents this at the
      source, so by the time _build_poly_fields runs there is nothing to
      overwrite.

      We cannot hook between _setup_base and _build_poly_fields in a live
      registry, so this test is structural: it verifies that after setup
      every poly-injected field that existed before _build_poly_fields
      ran is already related+non-stored.
      """
      if 'project.task' not in self.env or 'numa.planning.node' not in self.env:
          self.skipTest("project.task or numa.planning.node not in registry")
      task_cls = type(self.env['project.task'])
      # Walk the MRO and collect definition classes that belong to dep model hierarchies.
      from odoo.models import MetaModel
      dep_map = {}
      for base in task_cls.__mro__:
          raw = base.__dict__.get('_depend_models')
          if raw and isinstance(raw, dict):
              dep_map.update(raw)
      if not dep_map:
          self.skipTest("project.task has no _depend_models")
      # Gather definition classes from dep reg classes' MROs.
      foreign_def_cls = set()
      for dep_name in dep_map:
          dep_reg = self.env.registry.get(dep_name)
          if dep_reg is None:
              continue
          for c in type.mro(type(dep_reg)):
              if isinstance(c, MetaModel) and getattr(c, 'pool', None) is None:
                  foreign_def_cls.add(c)
      # Verify that none of the foreign def class fields appear as stored in project.task._fields.
      for fdc in foreign_def_cls:
          fd_list = getattr(fdc, '_field_definitions', []) or []
          for f in fd_list:
              fname = getattr(f, 'name', None)
              if fname is None:
                  continue
              field_in_task = self.env['project.task']._fields.get(fname)
              if field_in_task is not None:
                  self.assertFalse(
                      getattr(field_in_task, 'store', False) and
                      not getattr(field_in_task, 'related', None),
                      f"Field {fname} is stored/non-related in project.task — "
                      f"stale entry from {fdc} not eliminated at root"
                  )
  ```

- [ ] **Step 1.2 — Run test to confirm it currently passes (stale entries are cleaned up by existing code)**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  .venv/bin/python numa-public-odoo-18.0-numa/odoo-bin \
    --config odoo.config \
    --test-enable --stop-after-init \
    --test-tags poly_setup \
    -d cm-test-18.0 2>&1 | tail -30
  ```

  Expected: all poly_setup tests pass (including the new one, since the replacement already works).

- [ ] **Step 1.3 — Add `_poly_foreign_def_classes` helper function**

  Insert this function after the `_poly_collect_depend_models` function (around line 225 in poly.py):

  ```python
  def _poly_foreign_def_classes(cls) -> frozenset:
      """
      Return the set of definition classes (MetaModel instances with pool=None) that
      appear in cls.__mro__ because of Phase-1 dep model injection — NOT because they
      belong to cls's own class hierarchy.

      These are the classes whose _field_definitions would bleed into cls._fields during
      _setup_base if left unguarded.

      Algorithm: walk the MRO of each dep model registry class and collect its definition
      ancestors.  Any def class reachable from a dep reg class but NOT reachable from
      cls's own definition classes is "foreign".
      """
      from odoo.models import MetaModel

      dep_map = _poly_collect_depend_models(cls)
      if not dep_map:
          return frozenset()

      # Collect definition classes that are "own" to cls (from cls's non-dep ancestors).
      # These must NOT be excluded — they are cls's own field sources.
      pool = getattr(cls, 'pool', None)
      own_def_classes: set = set()
      for c in type.mro(cls):
          if c is cls:
              continue
          if isinstance(c, MetaModel) and getattr(c, 'pool', None) is None:
              # Check if this def class is reachable from any dep reg class.
              # If not, it's own.
              own_def_classes.add(c)

      # Collect definition classes reachable exclusively via dep reg class ancestry.
      foreign: set = set()
      for dep_name in dep_map:
          if pool is None:
              continue
          dep_reg = pool.get(dep_name)
          if dep_reg is None:
              continue
          for c in type.mro(type(dep_reg)):
              if isinstance(c, MetaModel) and getattr(c, 'pool', None) is None:
                  if c not in own_def_classes:
                      foreign.add(c)

      # Final filter: remove any that ARE in cls's own_def_classes to be safe.
      # (In practice own_def_classes already excludes them, but be explicit.)
      return frozenset(foreign - own_def_classes)
  ```

  > **Note:** The "own" vs "foreign" distinction relies on the fact that a def class from
  > `NumaPlanningNode`'s hierarchy is NOT a direct ancestor of `ProjectTask` (the def class
  > of `project.task`) — it only appeared in the MRO after Phase-1 injection of the registry
  > class.  This assumption holds because poly models use `_depend_models` instead of
  > Python inheritance for the polymorphic relationship.

- [ ] **Step 1.4 — Add `_PolyFieldGuard` context manager**

  Insert right after `_poly_foreign_def_classes` (still near the top of poly.py module-level
  functions, before `PolyBase` class definition):

  ```python
  class _PolyFieldGuard:
      """
      Context manager that temporarily blanks _field_definitions on all definition
      classes that are "foreign" to *cls* (i.e. they were pulled into cls.__mro__ by
      Phase-1 MRO injection, not by cls's own class hierarchy).

      While the guard is active, Odoo's _setup_base scans those classes but finds an
      empty _field_definitions list, so their fields are never added to cls._fields as
      stale stored entries.

      Usage::

          with _PolyFieldGuard(SomePolyClass):
              _original_BaseModel._setup_base(instance)
      """

      __slots__ = ('_saved',)

      def __init__(self, cls):
          self._saved: dict = {}
          for fdc in _poly_foreign_def_classes(cls):
              original = getattr(fdc, '_field_definitions', None)
              if original is not None:
                  self._saved[fdc] = original

      def __enter__(self):
          for fdc, _ in self._saved.items():
              fdc._field_definitions = []
          return self

      def __exit__(self, *_):
          for fdc, original in self._saved.items():
              fdc._field_definitions = original
  ```

- [ ] **Step 1.5 — Modify `PolyBase._setup_base` to use the guard**

  Current code (around line 1567):
  ```python
  def _setup_base(self):
      """Run standard Odoo field setup then inject polymorphic fields."""
      _original_BaseModel._setup_base(self)
      if _poly_is_polymorphic(type(self)):
          type(self)._build_poly_fields(calling_self=self)
  ```

  Replace with:
  ```python
  def _setup_base(self):
      """
      Run standard Odoo field setup then inject polymorphic fields.

      For polymorphic models, wrap the base _setup_base call in _PolyFieldGuard so
      that definition classes belonging to dep model hierarchies contribute an empty
      _field_definitions list.  This prevents stale stored entries from appearing in
      cls._fields before _build_poly_fields runs.
      """
      if _poly_is_polymorphic(type(self)):
          with _PolyFieldGuard(type(self)):
              _original_BaseModel._setup_base(self)
          type(self)._build_poly_fields(calling_self=self)
      else:
          _original_BaseModel._setup_base(self)
  ```

- [ ] **Step 1.6 — Simplify the skip guard in `_build_poly_fields`**

  Now that no stale entries are created, the tightened guard is no longer needed. The original
  simple guard ("skip if already poly-injected") is sufficient.

  Find this block in `_build_poly_fields` (around line 3290):
  ```python
  if fname in cls._fields:
      existing = cls._fields[fname]
      # Skip only if already correctly injected by poly (related and non-stored).
      # When Phase-1 MRO injection adds the depend model's registry class to
      # cls.__bases__, Odoo's _setup_base picks up the depend model's
      # _field_definitions and adds its fields as stored/non-related entries in
      # cls._fields.  We must replace those stale entries with the proper
      # poly-related version.
      if getattr(existing, '_poly_injected', False) and not getattr(existing, 'store', True):
          continue
      _logger.debug(
          '[poly] _build_poly_fields: replacing stale field %s in %s '
          '(related=%r, store=%r) with poly-related version',
          fname, cls._name,
          getattr(existing, 'related', 'N/A'),
          getattr(existing, 'store', 'N/A'),
      )
  ```

  Replace with the simpler:
  ```python
  if fname in cls._fields:
      existing = cls._fields[fname]
      if getattr(existing, '_poly_injected', False):
          continue  # Already correctly injected; skip.
  ```

- [ ] **Step 1.7 — Run tests to confirm all still green**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  .venv/bin/python numa-public-odoo-18.0-numa/odoo-bin \
    --config odoo.config \
    --test-enable --stop-after-init \
    --test-tags poly_setup \
    -d cm-test-18.0 2>&1 | tail -40
  ```

  Expected: all poly_setup tests pass (including `test_no_stale_stored_entry_before_poly_injection`).

- [ ] **Step 1.8 — Also run the improvements test suite**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  .venv/bin/python numa-public-odoo-18.0-numa/odoo-bin \
    --config odoo.config \
    --test-enable --stop-after-init \
    --test-tags numa_poly \
    -d cm-test-18.0 2>&1 | tail -40
  ```

  Expected: all numa_poly tests pass (no regressions in `TestPolyImprovements`).

- [ ] **Step 1.9 — Commit**

  ```bash
  cd /home/gamarino/odoo/numa-public-addons-18.0 && \
  git add numa_poly/models/poly.py numa_poly/tests/test_poly_setup.py && \
  git commit -m "$(cat <<'EOF'
  [numa_poly] Structural fix: _PolyFieldGuard eliminates stale-field root cause

  Problem: Phase-1 MRO injection added the dep model's registry class to the poly
  child's __bases__. The registry class inherits from the dep model's definition
  class (e.g. NumaPlanningNode), which has pool=None, so _setup_base picked up its
  _field_definitions and created stale stored entries in the child's _fields (e.g.
  pln_required_resource_ids with store=True).  The previous fix overwrote those stale
  entries inside _build_poly_fields — correct but treating a symptom.

  Fix: _PolyFieldGuard context manager (new) temporarily blanks _field_definitions on
  all definition classes that are foreign to the poly model (reachable only via dep
  registry class ancestry, not via the model's own hierarchy) before calling the
  standard _setup_base.  Stale entries are never created.

  _poly_foreign_def_classes (new) identifies those foreign definition classes by
  walking the dep model registry class MRO and excluding any def class that is also
  reachable from the poly model's own definition hierarchy.

  Consequence: the replacement logic in _build_poly_fields simplifies back to the
  original "skip if already _poly_injected" guard; the debug log for "replacing stale
  field" is removed as it should never fire.

  Test: test_no_stale_stored_entry_before_poly_injection added to test_poly_setup.py
  to assert that no stale stored/non-related entries survive for any field defined in
  a dep model's definition class hierarchy.

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 2 — Delete dead code: `_build_dependant_model_attributes`

**Problem:** `_build_dependant_model_attributes` is a 956-line `@classmethod` that was the
original field-injection route. It is called exclusively within itself (recursive invocations
for chained poly models). There is NO external call site — `_setup_base` uses
`_build_poly_fields` as the sole entry point. The function is dead code that adds maintenance
burden, carries the `_set_field` inner function that modifies `_field_definitions` (a potential
future regression vector), and confuses readers about the active injection strategy.

**Files:**
- Modify: `numa_poly/models/poly.py` (delete lines 2261–3217, remove `_poly_attributes_built` references)

- [ ] **Step 2.1 — Verify no external callers exist**

  ```bash
  grep -rn "_build_dependant_model_attributes" \
    /home/gamarino/odoo/numa-public-addons-18.0/ \
    --include="*.py" | grep -v "poly\.py"
  ```

  Expected: **no output** (zero matches outside poly.py).

  ```bash
  grep -rn "_poly_attributes_built" \
    /home/gamarino/odoo/numa-public-addons-18.0/ \
    --include="*.py"
  ```

  Expected: all matches inside `poly.py` only, all within the `_build_dependant_model_attributes` body.

- [ ] **Step 2.2 — Identify exact line range to delete**

  ```bash
  grep -n "def _build_dependant_model_attributes\|_logger.debug.*_build_dependant_model_attributes finished\|def _build_poly_fields" \
    /home/gamarino/odoo/numa-public-addons-18.0/numa_poly/models/poly.py
  ```

  Expected output (approximate):
  ```
  2261:    @classmethod
  2262:    def _build_dependant_model_attributes(cls):
  3216:        _logger.debug(f'_build_dependant_model_attributes finished')
  3218:    @classmethod
  3219:    def _build_poly_fields(cls, calling_self=None) -> None:
  ```

  The block to delete is from the `@classmethod` decorator on line 2261 through the blank line
  before `@classmethod` at line 3218 (inclusive of the trailing blank line).

- [ ] **Step 2.3 — Delete the function**

  Use the Edit tool to remove the entire `_build_dependant_model_attributes` block.
  The old_string starts with the `@classmethod` decorator and ends with the last `_logger.debug`
  line and trailing newline.

  Confirm: after deletion, `grep -n "_build_dependant_model_attributes" poly.py` returns zero
  matches in the code (only comments if any remain).

- [ ] **Step 2.4 — Remove any leftover references to `_poly_attributes_built`**

  ```bash
  grep -n "_poly_attributes_built" \
    /home/gamarino/odoo/numa-public-addons-18.0/numa_poly/models/poly.py
  ```

  If any remain (they should all be inside the deleted block), remove them.

- [ ] **Step 2.5 — Run tests to confirm all still green**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  .venv/bin/python numa-public-odoo-18.0-numa/odoo-bin \
    --config odoo.config \
    --test-enable --stop-after-init \
    --test-tags numa_poly \
    -d cm-test-18.0 2>&1 | tail -40
  ```

  Expected: all tests pass.  The deletion of a dead-code function must not affect behavior.

- [ ] **Step 2.6 — Commit**

  ```bash
  cd /home/gamarino/odoo/numa-public-addons-18.0 && \
  git add numa_poly/models/poly.py && \
  git commit -m "$(cat <<'EOF'
  [numa_poly] Remove dead code: _build_dependant_model_attributes (~960 lines)

  _build_dependant_model_attributes was the original field-injection route predating
  the current _build_poly_fields / _setup_base pipeline.  It had no external call
  sites — its only invocations were recursive (it called itself for chained poly
  models).  The active injection path has been _build_poly_fields (called from
  _setup_base) since the Odoo 18 migration.

  The function contained an internal _set_field helper that called __set_name__ and
  mutated _field_definitions directly — a pattern that would reproduce the stale-field
  problem if ever re-activated.  Removing it eliminates that latent risk.

  _poly_attributes_built (the per-class guard used by _build_dependant_model_attributes)
  is also removed as it has no meaning outside that function.

  No behaviour change: all tests pass unchanged.

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 3 — Consolidate and document the single injection route + cycle-token for `_poly_fields_built`

**Problem:** After Task 2, `_build_poly_fields` is the sole field-injection entry point.  However,
two secondary issues remain:

1. Comments and docstrings throughout poly.py still reference `_build_dependant_model_attributes`
   as a "legacy" or "alternate" route, creating misleading documentation.
2. The `_poly_fields_built` boolean flag has dual semantics (recursion guard + cycle guard) and
   requires explicit clearing before every `setup_models` call (in Phase 2).  A cycle counter
   token is more robust: it automatically becomes stale when the registry cycle counter advances,
   without needing a clearing loop.

**Files:**
- Modify: `numa_poly/models/poly.py` (docstrings, comment cleanup, cycle-token change)

- [ ] **Step 3.1 — Replace the `_poly_fields_built` boolean with a cycle-token integer**

  The idea: instead of storing `cls._poly_fields_built = True`, store
  `cls._poly_fields_built = <current_cycle_id>`.  Before `_build_poly_fields` runs, compare
  the stored value with the current cycle ID.  If they match, skip.  No explicit clearing loop
  is needed because a new `setup_models` call uses a new (higher) cycle ID.

  **3.1.a — Add a module-level cycle counter**

  Find the module-level variable section (near the other `_poly_*` variables at the top of
  `_poly_registry_setup_models` or as a module-level int) and add:

  ```python
  # Monotonically-increasing counter, incremented at the start of every
  # _poly_registry_setup_models call.  Used as a cycle token for _poly_fields_built
  # so that the guard is automatically invalidated across setup_models calls without
  # needing an explicit clearing loop.
  _poly_setup_cycle: int = 0
  ```

  Place this near the other module-level `_poly_*` definitions.

  **3.1.b — Increment at the top of `_poly_registry_setup_models`**

  At the very start of `_poly_registry_setup_models` (before Phase 0):

  ```python
  global _poly_setup_cycle
  _poly_setup_cycle += 1
  _current_cycle = _poly_setup_cycle
  ```

  **3.1.c — Replace `cls._poly_fields_built = True` in `_build_poly_fields`**

  There are three occurrences:
  - Early return for non-polymorphic models: `cls._poly_fields_built = True` → `cls._poly_fields_built = _poly_setup_cycle`
  - Recursion guard set: `cls._poly_fields_built = True` → `cls._poly_fields_built = _poly_setup_cycle`

  Guard check (currently `if getattr(cls, '_poly_fields_built', False): return`):
  ```python
  if getattr(cls, '_poly_fields_built', 0) == _poly_setup_cycle:
      return
  ```

  **3.1.d — Remove Phase-2 clearing loop from `_poly_registry_setup_models`**

  Find and delete the Phase-2 block that iterates over the registry to `delattr` `_poly_fields_built`:
  ```python
  # [poly] Phase 2: Clear the per-class _poly_fields_built flag before every
  # setup_models call ...
  for _cls in self.values():
      if isinstance(_cls, type) and '_poly_fields_built' in _cls.__dict__:
          try:
              delattr(_cls, '_poly_fields_built')
          except AttributeError:
              pass
  ```

  This loop is no longer needed because the cycle token automatically invalidates across calls.

- [ ] **Step 3.2 — Clean up comments referencing the legacy route**

  Search for all references to `_build_dependant_model_attributes` or the "legacy" route in
  comments:

  ```bash
  grep -n "dependant_model_attributes\|legacy.*injection\|legacy.*route\|_poly_attributes_built" \
    /home/gamarino/odoo/numa-public-addons-18.0/numa_poly/models/poly.py
  ```

  For each match: if it's in a comment or docstring referencing the deleted function, update or
  remove the reference.  Replace wording like "legacy route" with "historical note" or remove
  entirely if stale.

- [ ] **Step 3.3 — Update `_build_poly_fields` docstring to reflect it is the sole injection entry point**

  Find the docstring at line ~3219 and update:

  ```python
  def _build_poly_fields(cls, calling_self=None) -> None:
      """
      Inject polymorphic related fields into cls from its _depend_models chain.

      This is THE single field-injection entry point for numa_poly.  It is called
      from PolyBase._setup_base after the standard Odoo field setup has run (with
      _PolyFieldGuard active to prevent foreign definition-class fields from
      bleeding in as stale stored entries).

      Algorithm
      ---------
      1. Guard: skip ir.poly_base, non-polymorphic models, and models whose
         _poly_fields_built token matches the current setup cycle.
      2. Set _poly_fields_built = _poly_setup_cycle (cycle token) as recursion guard.
      3. Collect the consolidated dep_map via _poly_collect_depend_models.
      4. For each (base_model_name, link_field_name):
         a. Ensure the PolyReference link field exists in cls.
         b. Force _setup_base on the base if its _fields is empty.
         c. For every non-technical field in base._fields:
            - Resolve to its ultimate origin via _poly_resolve_field_origin.
            - Ensure a PolyReference to that origin exists in cls.
            - Inject a related=copy of the field (skip if already _poly_injected).
      5. Redirect any manually-written related fields that still use model-name prefixes.
      6. Inject infrastructure fields (poly_base_id and audit fields).
      """
  ```

- [ ] **Step 3.4 — Update `NewStrategy.md` to reflect both changes**

  In `numa_poly/doc/NewStrategy.md`:
  - In the setup phases table: remove Phase 2 (clear `_poly_fields_built`) and add note
    that the cycle token makes explicit clearing unnecessary.
  - In the field-injection section: remove the "legacy path" row; confirm only
    `_build_poly_fields` is listed.
  - Add a paragraph about `_PolyFieldGuard` and `_poly_foreign_def_classes` under the
    "Field Injection Pipeline" heading.

- [ ] **Step 3.5 — Run full test suite one final time**

  ```bash
  cd /home/gamarino/odoo/cm-18.0 && \
  .venv/bin/python numa-public-odoo-18.0-numa/odoo-bin \
    --config odoo.config \
    --test-enable --stop-after-init \
    --test-tags numa_poly \
    -d cm-test-18.0 2>&1 | tail -50
  ```

  Expected: all tests pass, including `test_no_stale_stored_entry_before_poly_injection`.

- [ ] **Step 3.6 — Commit**

  ```bash
  cd /home/gamarino/odoo/numa-public-addons-18.0 && \
  git add numa_poly/models/poly.py numa_poly/doc/NewStrategy.md && \
  git commit -m "$(cat <<'EOF'
  [numa_poly] Consolidate to single injection route + cycle-token for _poly_fields_built

  After removing _build_dependant_model_attributes, _build_poly_fields is now the
  sole field-injection entry point.  This commit completes the consolidation:

  1. _poly_fields_built boolean → cycle-token integer (_poly_setup_cycle).
     _poly_registry_setup_models increments a module-level counter at the start of
     each call.  _build_poly_fields stores the current counter value instead of True.
     The guard check compares stored value == current counter.  No explicit clearing
     loop (Phase 2) is needed: a new counter value automatically invalidates all
     previously set tokens.  The Phase-2 loop is removed.

  2. Stale comments and docstrings referencing _build_dependant_model_attributes as a
     "legacy route" are removed or updated.  _build_poly_fields docstring updated to
     state explicitly that it is THE single injection entry point.

  3. NewStrategy.md updated: Phase 2 removed from the phases table; _PolyFieldGuard
     and _poly_foreign_def_classes added to the field-injection pipeline section.

  No behaviour change: cycle-token semantics are equivalent to boolean + clearing
  loop, with less code and no risk of the clearing loop being skipped or forgotten.

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Self-Review

### Spec coverage
- [x] Improvement 1 (stale-field structural fix): Task 1 ✓
- [x] Improvement 2 (remove dead code): Task 2 ✓
- [x] Improvement 3 (consolidate injection routes + clean docstrings): Task 3 ✓

### Placeholder scan
- All steps contain exact code or exact commands.
- No "TBD" or "similar to above" patterns.

### Type / name consistency
- `_PolyFieldGuard` used consistently in Task 1 steps 1.4, 1.5.
- `_poly_foreign_def_classes` used consistently in Task 1 steps 1.3, 1.4, and the new test.
- `_poly_setup_cycle` and `_current_cycle` used consistently in Task 3 step 3.1.
- `_poly_fields_built` referred to by the same name throughout.
