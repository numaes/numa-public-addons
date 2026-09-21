# Lessons

Written during the Odoo 20.0 migration of `numa-public-addons`. One entry per mistake
worth not repeating, with the rule that prevents it.

## 1. A test that passes against the bug is not a test

Twice in one session a guard was written, went green, and proved nothing.

- A `DeprecationWarning`-based guard for `env.cache` passed with the bug present:
  `Environment.cache` is a `cached_property`, so the warning's `stacklevel` attributes
  it to `environments.py` and the assertion never saw it.
- A test asserting `field.compute and field.related` on a built field passed for every
  related field there is — Odoo sets `compute='_compute_related'` on all of them.

**Rule: verify every regression test red before believing it green.** Revert the fix
(`git stash push <file>`), run, confirm the failure names the right thing, restore.
For a whole-module rewrite, stash the module file and check how many of the new tests
fail — if it is one out of twelve, the other eleven are not testing what they claim.

## 2. `search()` returns an empty recordset, not `None`

`if last_ingress is None` was never true, so the `else` branch — the one that reads the
product instead of the previous delivery — was unreachable, and the code took the wrong
branch on the first record it saw.

**Rule: truthiness for recordsets (`if records:`), never an identity test against
`None`.**

## 3. Read what the field already means before converting it

Two modules converted `quantity_product_uom` / `product_uom_qty` a second time because
the name did not say they were already normalised to the product's unit. Core computes
both as `uom._compute_quantity(qty, product.uom_id)`. A line in dozens reported twelve
times its weight.

**Rule: before wrapping a core field in arithmetic, open its definition.** The one-line
`help` and the compute say what unit it is in.

## 4. An `@api.depends` on a plain method does nothing

It only means something on the method a field names as its `compute`. Four modules had
`@api.onchange` and `@api.depends` stacked on the same helper with plain stored fields
underneath, and the values therefore existed only when a human typed into a form.

**Rule: if a value must be right outside the form, it is a computed field.** An
onchange is a convenience for the form, never the mechanism.

## 5. Do not fork a core method to add two lines to it

`numa_poly._write_multi` was a full copy of core's, kept to append an audit stamp. The
copy fell a version behind on the SQL that merges a translated jsonb column, and every
translated field written through a polymorphic model was silently stored as a JSON
array. Nothing failed at write time.

**Rule: an override calls `super()` and adds its own part.** When core's body genuinely
has to change, the fork gets a comment naming the core version it was taken from and a
test that fails when core moves.

## 6. Run a module's suite against its own dependencies

`numa_synch`'s tests failed on a database where `numa_synch_ai_assisted` was installed,
because that module deliberately changes the behaviour being asserted. The tests were
right; the database was wrong.

**Rule: a fresh database with the module and its dependencies is the reference run.**
Where a sibling legitimately changes behaviour, assert the contract (it is refused) and
not the wording (which sibling reworded it).

## 7. Report a detected problem, do not silence it

A `continue` where core has an `assert`, a bare `except` around an `AttributeError`, a
`_logger.debug` on a failed cache write: each of these turned a loud failure into a
wrong answer that took a migration to find.

**Rule: when something unexpected is detected, raise or warn with enough detail to act
on.** Silence is only acceptable where the alternative is worse and the comment says why.
