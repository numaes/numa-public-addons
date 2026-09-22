# Backport to 18.0 — what of the 20.0 work goes back, and what does not

**Status: a plan, not work done.** Nothing here has been applied to
`numa-public-addons-18.0`. It exists so the backport can be started later without
re-deriving the analysis, and so the decisions it contains are argued once rather
than re-litigated per module.

---

## Status

**Batches 0, 1 and 2 are done**, on `numa-public-addons-18.0`, branch 18.0, six
commits ending `23deff1b` (2026-09-22). What executing them proved, and what it
corrected in this document, is in "What Batch 1 actually found" and "What Batch 2
actually found" below. Batch 3 onward is untouched.

---

## The whole plan on one screen

| # | What | Cost | Moves an interface? |
|---|---|---|---|
| **0** | ~~`numa_roles` grants **every user** CRUD on `res.groups`~~ **DONE** | one deleted line | no |
| 1 | ~~Four views with `attrs=` do not load in 18.0~~ **DONE** | small | no |
| 2 | ~~11 committed `__pycache__` files (Python 3.7)~~ **DONE** | trivial | no |
| 3 | ~~`numa_fsm_crm` / `numa_fsm_hr` controllers: four dead public routes, duplicated~~ **DONE** | delete | no |
| 4 | ~~`action_assign_bot` asks for `view_mode: tree`~~ **DONE** | one word | no |
| 5 | ~~`numa_imap` UID marker survives a duplicate~~ **DONE** | two words | no |
| 6 | ~~`numa_exceptions` overrides `_name_search`, removed in 17.0~~ **DONE** | delete | no |
| 7 | ~~An orphan test file in `numa_fixed_output_mail`~~ **DONE** | trivial | no |
| 8 | ~~`numa_fsm`'s seven orphan tests target a dead API~~ **DONE** | decide | no |
| **9** | ~~`numa_poly.create` drops unknown keys in silence~~ **DONE** | cherry-pick | no |
| **10** | ~~An injected related field carries the base's `default`~~ **DONE** | cherry-pick | no |
| **11** | ~~`_poly_native_field_names` counts every field~~ **DONE** | cherry-pick + check | no |
| 12 | `product.weight` / `.volume` unstored; the core reads them in SQL | two words | two new columns |
| 13 | `numa_big_id`: the int8 signatures PostgreSQL does not ship | cherry-pick | no |
| 14 | `numa_fixed_output_mail`: mail leaves through another company's mailbox | cherry-pick | behaviour |
| 15 | `numa_imap`'s `message_process` fork misses core loop detection | re-derive | no |
| 16 | `numa_roles`: a constraint that cannot fire, a counter that counts wrong | small | no |
| 17 | `numa_synch`: the protocol has never connected (7 defects, one a data leak) | mostly cherry-pick | the route only |
| 18 | `numa_fsm_pubsub` does not install; two things corrupt data | small | data rename — avoidable |
| 19 | `numa_product_variant`: two labels for the same product | re-derive | visible label |
| 20 | `numa_asynch_exec` starts a job while shutting down | re-derive | needs the cron too |
| 21 | The `_write_multi` fork drops the audit fields | cherry-pick | no |
| 22 | The four `physical_product` bridges do not price by weight | **a project** | columns, methods, labels |
| 23 | `numa_roles`: what NOT to port | — | — |
| 24 | `numa_fsm_*`: the redesign does NOT go back | — | — |

Items 0 to 11 can be done without asking anyone. Everything from 12 on changes
something a user can see, which is what a fix is; the column says whether it also
changes something they have written down.

---

## The premise, made operational

The instruction is: **do not move interfaces, so the changes do not cascade onto
users.** Sharpened enough to sort sixty commits by:

**Moving an interface** means changing something already written down elsewhere —
a model or field name, a method signature, an xmlid, a visible or translated
label, a database column, the meaning of a security group.

**Not moving an interface** — but still visible, because every real fix is —
means a wrong value becoming right, something that never ran starting to run, or
a record appearing that should have been there all along.

The question is never "does anything change?" but **"does anything a user has
already written down stop working?"**

---

## What was classified

61 commits on `20.0` that are not on `18.0`, of which 5 touch only `.md` files.

**The unit of backport is the finding, not the commit.** Most commits mix an
Odoo 20 API adaptation with a defect found while making it, in the same function.
Cherry-picking wholesale imports 20.0 APIs into an 18.0 branch. Every item below
names its own evidence in the 18.0 tree.

Everything marked **verified** was checked against `numa-public-addons-18.0` as
it stands on 2026-09-22, and where a platform claim is involved, against the Odoo
18 core.

---

## First, the shape of `numa_poly`, because it decides most of this

`numa_poly` was **not** rewritten for 20.0. It is the same file with the same
genealogy — 7420 lines in 18.0, 7558 in 20.0 — and much of the ~3200-line diff is
comments translated from Spanish to English. Function names and order match
almost one to one.

What did change is **the mechanism that injects the related fields**, and that is
the frontier every poly item falls on one side of:

| 20.0 | In 18.0? |
|---|---|
| `_poly_contribute_definitions()` | **no** |
| generated `PolyContribution_*` classes | **no** |
| `_poly_declared_inherits` / `_poly_declared_depends` / `_poly_declared_campos` | **no** |
| `_depend_models` | yes, identical |
| `_poly_native_field_names()` | yes, byte-identical but for the fix |
| `_poly_force_related()` | yes, near-identical |
| the `_write_multi` fork | yes, identical |

20.0 generates a synthetic contribution class and registers it in one pass before
setup. **18.0 mutates `__bases__` directly** and decides the related **lazily**,
in two monkeypatches (`poly_BaseModel_add_field` at 18.0 `poly.py:6275`,
`poly_Field_setup` at `poly.py:6286`).

So: **defects living in `_poly_contribute_definitions` are not cherry-pickable;
defects living in the shared functions are.**

---

## Batch 0 — one line, and it should not wait for the rest

0. **`numa_roles` grants every user full CRUD on `res.groups`.**
   `security/ir.model.access.csv`, verbatim in 18.0:
   ```
   access_res_groups_numa_roles,res.groups (Numa Roles),model_res_groups,,1,1,1,1
   ```
   The group column is **empty**, which means everyone. A module about access
   control is handing out the ability to create, edit and delete security groups
   to any user who can log in. Deleting the line is the whole fix and it moves no
   interface — it removes a permission nobody intended to grant.

   Verify what breaks: anything in `numa_roles` that writes `res.groups` as a
   plain user will start failing, and it should.

---

## Batch 1 — nothing observable changes

Zero interface risk beyond things that do not work starting to work.

1. **The four view files with `attrs=`.** `numa_synch_ai_assisted` (2),
   `numa_roles`, `numa_synch_slave`. Odoo **17** removed the attribute and 18.0's
   `ir_ui_view` raises a ValidationError, so **these views do not load in 18.0
   today**. Convert to the direct attributes, translating the domain to its
   Python expression.
2. **11 `__pycache__` files committed to the repository**, Python 3.7 bytecode, in
   `numa_background_job`, `numa_exceptions` and `numa_synch`. `git rm -r --cached`
   and add the ignore rule.
3. **`numa_fsm_crm/controllers/` and `numa_fsm_hr/controllers/` are dead and
   identical.** Verified byte-for-byte identical with `diff`: four `auth='public'`
   routes under `/crm_workflow/<wkf_id>` — the CRM paths, inside the HR module —
   against a model `crm.workflow` that does not exist, calling `consume_event()`
   which does not exist, rendering `numa_fsm.error_page` which is not declared,
   and reading `request.jsonrequest`, removed years ago. **Every route dies on its
   first statement, and the two modules register the same paths.** Delete both
   directories; what they were reaching for is `numa_fsm`'s
   `/fsm/form/<instance_uuid>`.
4. **`action_assign_bot` asks for `view_mode: 'tree,form'`.** The view type has
   been `list` since 17.0, so the action fails in 18.0 as well.
5. **`numa_imap`'s `last_uid` / `last_uid_validity` are bare Integers**
   (`models/fetchmail.py:24-25`). Duplicating a mail server carries the marker
   across, and the copy then skips every message older than a UID that belongs to
   a different mailbox. `readonly=True, copy=False` — one line each, no schema
   change.
6. **`numa_exceptions/models/exceptions.py:94` overrides `_name_search`**, which
   Odoo 17 replaced with `_search_display_name`. Verified that nothing calls it —
   not the core, not the module. Dead code that reads as live. Delete it, or port
   the body to `_search_display_name` **only if the search behaviour it describes
   is wanted**; that is a Batch 3 decision, not this one.
7. **`numa_fixed_output_mail/tests/test_force_sender.py` is never imported**; its
   `tests/__init__.py` holds nothing but a licence comment. Add it, expect red.
8. **`numa_fsm`'s seven unimported test files are a different case.** Its
   `tests/__init__.py` says in so many words that they target a dead API
   (`text_definition`, `onchange_text_definition`, `json_logic_schema`,
   `consume_event`) and are kept as reference. **Delete them or move them out of
   `tests/`**, do not import them. Read a module's `tests/__init__.py` before
   assuming an orphan is an accident.

**Deliberately not in this batch:** `<tree>` → `<list>` (5 files; both spellings
valid in 18.0) and `_sql_constraints` → `models.Constraint` / `models.UniqueIndex`
(6 files; `_sql_constraints` **works** in 18.0 — see "Traps").

---

## What Batch 1 actually found, and what it corrects here

Executing batches 0 and 1 on a database built from nothing contradicted this
document in four places. They are corrected above; they are listed here because
each says something about how the rest of the plan should be read.

**Four of the eleven affected modules did not install at all.** The plan named
single defects; modules that have not been installed in years have them stacked,
and each one hides the next. `numa_roles` took six passes: `attrs=` in two
spellings, four page anchors renamed (`view_access`/`rule_groups`/`menu_access`/
`implied_ids` → `views`/`record_rules`/`menus`/`inherit_groups`), a list view
inheriting an xmlid Odoo 18 does not declare, and a search filter that does not
exist. Budget for the tail, not for the item.

**`<tree>` is NOT valid in 18.0.** This document said both spellings work and put
the conversion under "deliberately not in this batch". Odoo 18 answers
`Invalid view type: 'tree'. Allowed types are: list, form, graph, pivot,
calendar, kanban, search, qweb, hierarchy, activity`. Nine tags in four files;
they had to be converted.

**`view_mode: tree,form` is worse than the plan said.** Not one action in
`numa_fsm_hr` but **nine actions across seven modules**, five of which install
perfectly well today — `view_mode` is a Char, so nothing fails at install and
the menu simply does not open when a user clicks it.

**`fetchmail` is not a module in Odoo 18.** This document said it still was, and
filed `numa_imap`'s hook split under "does not go back" on that basis.
`fetchmail.server` lives in `mail` since 17.0. `numa_imap` declared
`'depends': ['base', 'fetchmail']` and was therefore **uninstallable**, and its
view inherited `fetchmail.view_email_server_form`. Both corrected. Item 15 (the
`message_process` fork) is unaffected and still stands.

**Three defects the plan did not know about**, all of the same class — the
module cannot load:
- `numa_synch_slave`, `numa_synch_master` and `numa_synch_ai_assisted` all
  extend the abstract `numa.synch.engine` as `models.Model`, which Odoo refuses
  outright. This is listed in the project notes as a 20.0 breakage; it is a 17.0
  one.
- `numa_synch_slave`'s cron sets `numbercall` and `doall`, removed in 17.0.
- `numa_roles`'s list view inherits `base.view_groups_tree`, which does not
  exist.

**Two of the "live" orphan tests were not live.** `test_fsm_form_input` builds
`fsm.form_input` records with `instance_id` and `unrelated_identifier`; the model
has `name` and `json_event`. It joined the deleted pile. `test_fsm_templates` was
worth keeping — two of its six tests pass — but the other four need a complete
`fsm.definition` fixture that `common.py` does not build, and are skipped with
that reason on each. `numa_fixed_output_mail`'s orphan references demo records
that were never written anywhere, and is skipped with that reason.

### The 18.0 baseline, now that there is one

Measured on databases built from nothing, after Batch 1:

| Module | Suite on 18.0 |
|---|---|
| `numa_poly` | **0 of 134** — with `project`, `numa_planning` and `numa_planning_purchase` installed |
| `numa_poly_test` | 0 of 93 (82 before Batch 2) |
| `numa_planning` | 0 of 174 |
| `numa_planning_project` / `_purchase` | 0 of 7 each |
| `numa_fsm` | 0 of 62 (was 56; two previously unrun tests now pass, four skipped) |
| `numa_fsm_crm` | 0 of 3 |
| `numa_fsm_hr` | 0 of 2 |
| `numa_fixed_output_mail` | 0 of 4, all skipped |
| `numa_background_job` | 0 of 0 — it has a test file and runs nothing |

**`numa_poly` is green on 18.0: 0 of 134.** That is the number Batch 2 has to
preserve.

Getting it took two corrections worth recording, because both are traps for
anyone measuring a baseline. On a fresh database with **only** `numa_poly`
installed the suite reports 2 failed and 18 errors, and none of the twenty is a
defect:
- The 18 errors are all `KeyError: 'project.task'`. `numa_poly`'s own suite
  exercises the polymorphic machinery through `project.task` and
  `numa.planning.*`, so it needs `project` (core) and `numa_planning` — which
  lives in the **private** repository. A public module's suite depending on a
  private module is worth knowing on its own.
- The last failure, `TestPolyIdSpace.test_03_claiming_is_idempotent`, asserts
  that claiming the shared id space twice changes nothing. It assumes
  `res_partner` is **already** claimed when it starts, and `res.partner` only
  becomes polymorphic when `numa_planning_purchase` is installed. Without it the
  first claim legitimately changes the column default and the test reads that as
  a defect.

So the database Batch 2 must be measured on is: `numa_poly`, `project`,
`numa_planning`, `numa_planning_project`, `numa_planning_purchase`. Anything
less and the suite invents failures.

One more thing to know before Batch 2: on a database where `numa_poly` and
`numa_fsm_crm` are both installed, a test run can die in poly's own strict view
validation with `action_sale_quotations_new is not a valid action on crm.lead`,
even with `sale_crm` installed and the method present at runtime. It is an
ordering problem in `_poly_finalize_view_validation`, it predates this work, and
it makes some suites unrunnable on that combination.

---

## Batch 2 — `numa_poly`, the three that cherry-pick

The highest-value items in this repository: three defects in the module every
other module in both repositories stands on. All three in shared functions, all
three verified present.

9. **`create` drops unknown keys in silence.** 18.0 `poly.py:4100`, in
   `PolyBase.create`, right after `base_model.check_access('create')`. A key
   belonging to no model in the graph is never dispatched and nobody is told. The
   20.0 guard cherry-picks; the helper it needs (`poly_vals_propagados`, 18.0
   `poly.py:104`) already exists, and only the `_POLY_CREATE_TECHNICAL_KEYS`
   constant comes with it.
   In 20.0 this guard, once in place, immediately surfaced six real channels that
   had been losing fields. Expect the same: **the guard is the cheap part, what it
   reveals is the work.**

10. **An injected related field carries the base field's `default`.** Verified:
    `_poly_force_related` (18.0 `poly.py:246`) sets `args['store']`,
    `args['precompute']`, `field.related`, `field.store`, `field.precompute`,
    `field.compute`, `field.compute_sudo`, `field.inverse`, `field.search` — and
    **never touches `default`**. Odoo merges same-named field attributes along
    the MRO, so the injected field comes out `related` *and* defaulted, and
    writing a related field writes through to its target. Creating a polymorphic
    child against an existing base row overwrites values that row already held.
    Partial, because the third injection path, `_build_poly_fields`
    (18.0 `poly.py:3885`), *does* clear it. Two lines in `_poly_force_related`,
    plus the companion change in `_poly_field_default_value` (18.0 `poly.py:794`),
    which reads `field.default` where it should read `field.related_field.default`.
    **This is the one with the worst failure mode.** In 20.0 it meant every
    inbound Twilio message was stored as outgoing.

11. **`_poly_native_field_names` counts any field, not only declared ones.**
    Verified at 18.0 `poly.py:3724`: `for klass in cls.mro():` with nothing but a
    `dep_models` skip. The aggregate registry class is in that MRO and carries
    every field, so "native" means "everything" and dead columns stay alive.
    Cherry-picks with **one adaptation**: Odoo 18 spells the index
    `MetaModel.module_to_models`, not `_module_to_models__`.
    **Do not apply this one alone** — see the dependency below.

### The dependency between 10, 11, and the one that does not go back

The 20.0 defect where *a bridge's own compute was replaced by a related field*
(`ec1a61d`) **does not exist in 18.0**: it lives entirely inside
`_poly_contribute_definitions`, and 18.0 decides the no-shadow rule late, inside
`poly_Field_setup` (18.0 `poly.py:6346`), by which time the bridge's class is
already linked into the MRO.

But it is also **masked** by item 11: with "native" meaning "everything", 18.0
errs towards protecting too much, never too little. **Applying item 11 removes
that accidental protection.** Item 11 must therefore ship with a check that no
bridge loses its own compute — `numa_planning_purchase`'s
`purchase.order.line.pln_constraint_date` is the case, and 18.0's own
`numa_poly/tests/test_poly_no_shadow.py:32` is the test that watches it.

---

## What Batch 2 actually found

All three were present and all three are in. Two things are worth carrying
forward.

**The symptom of item 11 is not what you see from a shell.** `_poly_native_field_names`
is cached, and the cache is filled during registry setup, when the aggregate
class is not yet populated. Asking for the value afterwards returns the cached,
correct answer; **recomputing** it returns 43 extra names for `project.task`,
among them the whole `pln_*` set. A first measurement that read the cache said
the defect was absent. It is not — the answer simply depends on when it is
asked, which is the defect. The test clears the cache before asking, twice.

**The dependency the plan warned about is satisfied, and was checked rather than
assumed.** With the filter in place, `purchase.order.line.pln_constraint_date`
is still not related, still carries its own `_compute_` and `_inverse_`, and is
still native, while `project.task.pln_constraint_type` correctly resolves to
`planning_node_id.pln_constraint_type`. The filter keeps the classes a module
declared, so a bridge stays protected by its declaration instead of by an
accident of the scan.

**The 18.0 tests live in `numa_poly_test`**, with a `base_defaulted` field added
to `test.poly.base` so the default case can be exercised without any module from
outside this repository. Eleven tests across three classes. Each of the three
fixes was seen red on its own:

| Fix removed | Test that fails |
|---|---|
| the create guard | `test_01_un_create_con_campo_inexistente_falla` |
| `default = None` | `test_01_el_related_inyectado_no_tiene_default`, `test_03_un_valor_explicito_de_la_base_sobrevive` |
| the declared-classes filter | `test_02_un_campo_de_la_base_no_es_nativo_aunque_la_clase_lo_lleve` |

Green together: `numa_poly` 0 of 134 (baseline preserved), `numa_poly_test` 0 of
93 (82 + 11), `numa_planning` 0 of 174, `numa_planning_project` 0 of 7,
`numa_planning_purchase` 0 of 7.

---

## Batch 3 — a value that was wrong becomes right

12. **`product.product.weight` and `.volume` are not stored**
    (`numa_physical_product/models/product_product.py:24-33`: `compute="get_weight"`
    / `"get_volume"`, no `store`). The Odoo core reads both **raw in SQL**:
    `sale.report` does `SUM(p.weight * …)` over `product_product`
    (core 18 `addons/sale/report/sale_report.py:154`), and `purchase.report` the
    same (`purchase_report.py:86`). In the core these are real columns. Without
    them the report view cannot be created: installing this module before `sale`
    breaks `sale`'s install, and after it leaves a database whose sales report
    breaks the next time the view is rebuilt.
    **The fix is `store=True` on those two fields.** Two new columns the compute
    fills by itself during the upgrade; no field, label or signature moves.
    **The cheapest item on this list.**

13. **`numa_big_id`: the int8 signatures PostgreSQL does not ship.** Widening
    every `integer` to `bigint` — the module's declared design, `hooks.py:269`
    `migrate_to_bigint` and `models/big_int_patch.py:97` — takes columns outside
    the types accepted by two functions the core calls in SQL:
    `ROUND(SUM(part.debit_amount_currency), curr.decimal_places)` and
    `BOOL_OR(COALESCE(BOOL(pay.id), FALSE))`. PostgreSQL ships
    `round(numeric, integer)` and `bool(integer)` and no int8 equivalent, and
    there is no int8→boolean cast. Invoice creation, tax synchronisation and
    reconciliation all break. Verified the same calls in the Odoo 18 core
    (`addons/account/models/account_move.py:1143`,
    `account_move_line.py:730`).
    **Cherry-picks directly**: `_BIGINT_OVERLOADS` plus `ensure_bigint_overloads(cr)`
    from `pre_init_hook` (18.0 already has the `pre_init_hook(env)` signature,
    `hooks.py:480`) and from the final sweep. Creates two SQL functions in
    `public` that shadow nothing, and it is idempotent. **No interface moves at
    all.**

14. **`numa_fixed_output_mail` — two defects, both verified.**
    - `self.company_id` on `ir.mail_server`: **that field does not exist and never
      did, in 18 or 20**. The `AttributeError` lands in the `except Exception`
      wrapping the rewrite, so the message is returned untouched — exactly the
      case the branch exists for. `models/ir_mail_server.py`,
      `_force_sender_on_message`.
    - **A company's mail can leave through another company's mailbox.**
      `_find_mail_server` returns a server even when nothing matches (the first
      without `from_filter`, or any). Forcing the sender onto that fallback sends
      one company's mail from another's address, silently. Same behaviour in the
      Odoo 18 core.
    Everything the fix uses exists in Odoo 18: `_match_from_filter`
    (core `ir_mail_server.py:677`), `email_normalize` / `email_domain_extract`
    (`tools/mail.py:700,813`), `mail.alias.domain.company_ids`. The two added
    methods carry a `_numa_` prefix. **No schema, no field, no migration** — but
    it is an observable behaviour change: mail that goes out today (through the
    wrong mailbox) stops being forced and logs a warning. The view's new warning
    label is optional and can be left out of the backport.

15. **`numa_imap`'s `message_process` is a fork that drifted.**
    `models/fetchmail.py:140-215` is a copy of an older core with the
    save-a-copy step inserted in the middle. The Odoo 18 core
    (`addons/mail/models/mail_thread.py:1395-1429`) has since gained three things
    the fork does not have and nothing announces: deduplication by
    `x_odoo_message_id` as well as `Message-Id`, `_detect_loop_headers` (bounce
    loops) and `_detect_loop_sender` (sender loops). **Any database with
    `numa_imap` installed is not detecting either kind of mail loop.**
    The fix is the same move as in 20.0: do only the extra work and delegate the
    rest to `super()`. **This restores core behaviour rather than departing from
    it**, so it moves nothing.
    *Not backportable from the same commit:* the UID reading and the
    `fetch_mail` / `_fetch_mails` split. Verified that 18.0 **already** reads by
    UID with `BODY.PEEK[]` and keeps the marker (`fetchmail.py:67-100`), and that
    `fetchmail` is still its own module in 18.0.

16. **`numa_roles`, beyond Batch 0.**
    - `_check_technical_code_immutable` (`models/res_groups.py:147`) compares
      `technical_code` with `_origin.technical_code`; on a stored record
      `_origin` returns the record itself, so **the constraint can never fire**.
      Re-derive as a `write()` that compares against the stored value.
    - `permission_count` (`models/res_groups.py:61`) counts only direct
      `implied_ids`, so a role built from roles reports zero. `all_implied_ids`.

---

## Batch 4 — real, and each needs a conversation

17. **`numa_synch`: the Master/Slave protocol has never connected.** Seven
    defects, all verified present in 18.0:
    | defect | 18.0 |
    |---|---|
    | `request.jsonrequest`, removed in 17.0, first line of the endpoint, inside a blind `except` that answers errors with HTTP 200 | `numa_synch_master/controllers/main.py:61` |
    | `with self.env.context(sync_mode=True, …)` — `env.context` is a read-only mapping, neither callable nor a context manager | `numa_synch_master/models/numa_synch_engine.py:77` |
    | `model = self.env[model_name]; if not model:` — an empty recordset is falsy, so **every model of every batch is discarded** as "does not exist" | `..._master/models/numa_synch_engine.py:222` |
    | Test Connection reads only `response.status_code`, and the Master answers rejections with 200 → "Connection test successful!" with an invalid token | `numa_synch_slave/models/numa_synch_connection.py:294` |
    | The dependency walk appends whatever it reaches, so a rule on `res.partner` drags `res.users` in and serialises all its fields onto the wire. **Data leak.** | `..._slave/models/numa_synch_engine.py:281` |
    | `ValidationError` never imported → the domain-filter constraint dies with `NameError` instead of rejecting | `numa_synch/models/numa_synch_rule.py:163` |
    | `numa_synch_ai_assisted` catches `UserError` — i.e. every rejection — and hands the AI a version mismatch it cannot repair; falling off the loop returns `None`, read as "validated" | `numa_synch_ai_assisted/models/numa_synch_engine.py:47,96` |
    Six of the seven cherry-pick. **The seventh moves an interface**: the route
    `/numa_synch/api/v1/sync_batch` goes from `type='json'` + `auth='user'` to
    flat HTTP + bearer, which is an API contract change — and `type='json2'`
    **does not exist in Odoo 18**, so it has to be re-derived as `type='http'`
    with hand-rolled parsing. In practice no Slave is deployed against the old
    route, precisely because it never connected; confirm that before changing it.
    **Do not port** the `_sql_constraints` → `models.UniqueIndex` change: in 18.0
    the unique index does exist, and converting moves the schema for nothing.

18. **`numa_fsm_pubsub` does not install, and two things corrupt data.**
    All five verified in 18.0:
    - The module's own data violates its own constraint: topic `system.ping`
      (`data/fsm_topic_data.xml:14`) against `_check_name_format`
      (`models/fsm_topic.py:73`), which requires
      `name.replace('_','').replace('-','').isalnum()` — the dot fails.
      **The module does not install.**
    - The dispatcher builds `_handle_topic_{topic_name}` →
      `_handle_topic_system.ping`, not a possible Python name; the handler the
      module ships is `_handle_topic_system_ping` and is **unreachable**
      (`models/fsm_instance.py:187` vs `:269`).
    - `import datetime` inside an `ir.actions.server` body
      (`data/ir_actions_server.xml:13`) — `IMPORT_NAME` is a forbidden opcode in
      safe_eval.
    - Both subscription counters never refresh: one depends on `name` (not what
      it reads), the other on nothing (`models/fsm_topic.py:51`,
      `models/fsm_instance.py:27`).
    - The `is_active` constraint does not depend on `is_active`, so reactivating
      a subscription against a closed topic passes (`models/fsm_subscription.py:53`).
    **This is the most delicate item in the plan.** The 20.0 fix renames the topic
    to `system_ping` — a data record's `name`, and with it any
    `publish('system.ping', …)` a client has written — and tightens
    `TOPIC_NAME_RE` to `^[a-z][a-z0-9_]*$`, which forbids hyphens that 18.0
    accepted. **A cheaper route exists**: normalise only in the dispatcher's
    lookup, or accept dots in the regex and convert when building the method
    name. That fixes the defect without moving the data. Recommended.

19. **`numa_product_variant` overrides `name_get`, which Odoo 17 removed.**
    18.0 `models/product.py:30`. The core never calls it, so the label a user
    sees in a many2one comes from `_compute_display_name` — plain `name`, with no
    `[base_code]` prefix. But `name_search` (line 41, still live, and defined on
    the same class) ends in `.search(...).name_get()`, so it resolves to the
    module's own override: **the same product shows `[CODE] Name` while you are
    typing and `Name` once you have picked it.** Porting the body to
    `_compute_display_name` makes it consistent — and **changes the label of every
    product template with a `base_code`, everywhere in the UI**. No name, field or
    schema moves; the visible value does. Worth a sentence to whoever uses it.
    Note: 18.0 has `_compute_display_name` and `_search_display_name`, but **not**
    `odoo.fields.Domain` — return lists and use `expression.OR/AND`.

20. **`numa_asynch_exec` starts a job while the process is shutting down.**
    Verified: 18.0 `utils.py:11` creates the pool at module import, not lazily;
    the worker `_run_in_thread` (`utils.py:57`) opens a cursor in its first useful
    line (`utils.py:64`). No `atexit`, no `_shutting_down` flag.
    **Re-derive, not cherry-pick** — the module was reorganised in 20.0.
    **The caveat that decides it:** 20.0's fix is safe because a recovery cron
    picks the skipped job up five minutes later. **That cron does not exist in
    18.0** — there is no `data/` directory and `_recover_pending_jobs`
    (`models/asynch_job.py:95`) is called only from the `post_init_hook`. Porting
    the flag alone turns "dies with a confusing error" into "never runs at all".
    **Either bring the cron too, or do not do this.**

21. **The `_write_multi` fork is one version behind, differently.**
    18.0 `poly.py:5235`. The jsonb corruption that made this urgent in 20.0 **does
    not apply**: the copied SQL is character-for-character the Odoo 18 core's
    (`odoo/models.py:4862`). Two other defects of the same fork do:
    - the magic-field block is missing — the core writes `write_uid` /
      `write_date` under `if self._log_access` (core 18 `models.py:4827`) and the
      fork jumps from `_parent_store_update_prepare` straight to
      `updates = defaultdict(list)` (18.0 `poly.py:5261-5266`). **Audit fields are
      not being written on this path.**
    - the core's `assert field.store and field.column_type` is replaced by a
      silent `continue` (18.0 `poly.py:5284`).
    The 20.0 fix — delete the fork, call `super()`, keep the two stamping lines
    (18.0 `poly.py:5355`) — transplants directly. **Caveat:** dropping the fork
    re-enables that assertion. It was verified in 20.0 that no poly path feeds a
    column-less field into `vals`; that has **not** been verified in 18.0. Do that
    first.

---

## Needs a decision before it can go back

22. **The four `numa_physical_product_*` bridges did not price by weight.**
    The defect is real and expensive: `total_surface/weight/volume` and
    `price_qty` are stored fields filled **only by `@api.onchange`**, with an
    `@api.depends` stacked on the same method — which does nothing outside a
    compute. **Every line created outside the form** — a quotation template, an
    import, the API, a duplicate, invoicing from a sale or purchase order — gets
    `price_qty = 0`, and `price_qty` is what feeds the taxable base. Verified in
    all four modules, plus: `numa_physical_product_invoice` has no `write()` at
    all, so editing a quantity by code leaves the old taxable base; and
    `sale.update_prices` is **dead in 18.0** because the core method has been
    `_recompute_prices` since Odoo 18, so the "Update prices" button does not
    refresh `price_qty`.
    **This is the most expensive item in the plan and it moves several
    interfaces:**
    - `stock.move.line.unit_weight/unit_surface/unit_volume` go from unstored
      related to **new columns**; the `total_*` fields on `stock.move`,
      `sale.order.line`, `purchase.order.line` and `account.move.line` become
      computed-and-stored, so **Odoo recomputes them during the upgrade and
      overwrites values typed by hand** — the real historical weights. A
      deliberate backfill is required.
    - Public methods disappear: `compute_totals`, `compute_price`,
      `onchange_move_line_ids`, `_onchange_quantity`, `onchange_total_physicals`,
      `sale.order.update_prices`, `StockPicking.button_validate`.
    - Two visible labels change (`stock.move.line.partner_id` 'Empresa'→'Partner',
      `sale_order_id` 'Pedido'→'Sale Order'). **Do not port those.**
    **Proposal:** treat this as its own project with its own data plan, not as
    part of the backport. What can go in earlier and cheaply is item 12
    (`store=True` on weight and volume), which is independent.

23. **`numa_roles`: what not to port.** Beyond item 16, the 20.0 commit also
    moves the sample records from `data` to `demo` — which **deletes existing
    records during the upgrade** on a database that has them — retranslates the
    labels from Spanish to English (`'Tipo'`→`'Type'`,
    `'Código Técnico'`→`'Technical Code'`, `'Rol'/'Permiso'/'Sistema'`; the
    selection *keys* do not change, only what the user reads), drops `readonly`
    from `technical_code`, rebuilds the views and menus, and adds a new public
    API `has_permission()`. None of that belongs in a backport under this premise.

24. **`numa_fsm_hr` / `numa_fsm_crm`: the redesign does not go back.** "The lead
    HAS an FSM instance instead of BEING one" exists because
    `_inherit = ['crm.lead', 'fsm.instance']` stops linearising in Odoo 20.
    **In 18.0 it works** — numa_poly rebuilt `__bases__` by hand and undid the
    conflict on the way. Porting the redesign would turn `fsm_state`,
    `current_state_id`, `instance_variables`, `debug_mode` and `next_node_id` from
    own columns into related fields and require **migrating every existing FSM
    record of every employee and lead**. There is no reason. Items 3 and 4 are
    what goes back from these two modules.

## What does not go back

- **Every Odoo 20 API adaptation**: `_table_query` → `_table_sql`,
  `ir.model.access`/`ir.rule` → `ir.access`, `ir.attachment.datas` → `raw`,
  the typed `ir.config_parameter` accessors, `name_get` →
  `_compute_display_name` *as a mechanical rename*, `odoo.osv` → `fields.Domain`,
  `AbstractModel` subclassing, the manifest series string. In 18.0 the old
  spelling is the correct one — with the exception of items 6 and 19, where the
  18.0 code is already wrong *for 18.0*.
- **The `numa_poly` redesign itself** (the contribution class, the declared-name
  index, the MRO fix for a late-arriving base). The mechanism it replaces works
  in 18.0 and resolves the same C3 conflict by the opposite route — 18.0 *drops*
  redundant ancestor bases (18.0 `poly.py:6990`) where 20.0 *re-lists* the mixins
  behind them.
- **The bridge-compute fix** (`ec1a61d`), for the reason in the dependency note
  above.
- **`numa_fsm_crm` / `numa_fsm_hr`: the redesign** — see item 24.
- **`numa_imap`'s UID read and the `fetch_mail` split.** Verified that 18.0
  already reads by UID with `BODY.PEEK[]` and keeps the marker
  (`fetchmail.py:67-100`); the "set-then-clear" the 20.0 commit criticises is not
  there. The hook split follows a `fetch_mail` / `_fetch_mails` / `_fetch_mail`
  refactor that is Odoo 20's.
  *Corrected during Batch 1:* this entry used to add "and `fetchmail` is still its
  own module in 18.0". It is not — `fetchmail.server` moved into `mail` in 17.0,
  which is why `numa_imap` could not be installed at all.
- **`numa_product_variant`'s other four breakages** (`ir.access.csv`,
  `sale.prod_config_main`, `product.product_category_all`,
  `_is_combination_possible(parent_combination=…)`, the missing `categ_id`
  default, the positional controller arguments and the whole JS side). Verified
  each against the Odoo 18 core: all are 20.0-only. Two of the six are real — see
  item 19.
- **`numa_periodic_services`** — deleted in 20.0 as unused. Deleting a module in
  18.0 is a separate decision with its own blast radius.
- **Everything in the 20.0 commits that is comment translation.** A large part of
  the `numa_poly` diff is Spanish comments rendered into English. Worth doing
  some day; not worth a conflict on a live branch today.

---

## Traps

- **`_sql_constraints` → `models.Constraint` (6 files).** Ignored in Odoo 20,
  which is why it had to move. **In 18.0 it works.** Converting fixes nothing and
  starts enforcing constraints the database has never had — a populated database
  that violates one would refuse the upgrade. In 20.0 that was the right failure
  because the constraint was dead anyway; here it is gratuitous.
- **The `_write_multi` jsonb corruption.** Real and severe in 20.0; **not present
  in 18.0**, where the copied SQL is current. Do not port it as a bug fix — port
  the *other* two defects of the same fork (item 21).
- **Cherry-picking whole commits.** Most mix API adaptation with a real fix in
  the same hunk.
- **Test files that were not imported.** Sometimes an accident (item 7),
  sometimes a documented decision (item 8). Read the `__init__.py` before acting.
- **`_sql_constraints` in `numa_synch` and `numa_fsm_pubsub` specifically.** Both
  20.0 commits convert them to `models.UniqueIndex` and describe a double-delivery
  the missing index allowed. **In 18.0 the index exists**, because 18.0 honours
  `_sql_constraints` — so the double-delivery does not happen and the conversion
  would move the schema for nothing.
- **A defect that only appears because the *test* ran for the first time.** Many
  20.0 test changes adapt fixtures to Odoo 20. What is worth taking is the *case*,
  re-expressed against 18.0 — not the fixture.

---

## Fourteen modules got their first tests in 20.0

`numa_asynch_exec`, `numa_exceptions`, `numa_fsm_pubsub`, `numa_imap`,
`numa_physical_product_invoice`, `numa_physical_product_purchase`,
`numa_physical_product_sale`, `numa_physical_product_stock`, `numa_roles`,
`numa_synch`, `numa_synch_ai_assisted`, `numa_synch_master`, `numa_synch_slave`,
plus the new `numa_real_time_observability_test`.

These suites are where most of the migration's findings came from, and **the
cases they cover apply to 18.0 unchanged** even though the fixtures do not. This
is the largest piece of value in the whole backport and the one with the least
risk: a test changes nothing a user can see.

It is also the most work. Suggested approach: port them **module by module,
behind whichever batch touches that module**, rather than as a project of their
own. A suite that arrives with the fix it was written for is worth more than a
suite that arrives alone.

---

## Order of work, and why

1. **Batch 0, today.** One deleted line. Every user of a database with
   `numa_roles` installed can currently edit security groups.
2. **Batch 1** — no permission needed, and the repository stops carrying 2019
   bytecode, views that do not load and four public HTTP routes that die on their
   first statement.
3. **Batch 2** — items 9, 10 and 11 together, with the no-shadow check item 11
   requires. This is the core of the backport: three defects in the module every
   other module in both repositories stands on.
4. **Batch 3** — item 12 first (it is two words and it unbreaks the sales
   report), then 13, then 14, 15 and 16.
5. **Batch 4** — 17 without the route change; 18 by the cheaper route, not the
   rename; 19 after telling whoever uses `base_code`; 20 only with the cron; 21
   after verifying the assertion premise.
6. **The decisions** (22, 23, 24) — 22 is a project, not a batch. Say so, and
   schedule it separately.
7. **The test suites**, alongside whichever batch touches their module.

---

## How to verify

- **A backported fix is not believed until its test has been seen red.** Break it
  on purpose, watch exactly the expected tests fail, restore it. In 20.0 a fix
  for item 10 came out green in *both* directions on the first attempt, which
  proved nothing and meant it was at the wrong layer; it was reverted and redone.
- **`numa_poly` is the floor everything else stands on.** Its suite
  (`numa_poly_test`) has to be green before and after every item in Batch 2, on a
  database that was **rebuilt**, not updated: in 20.0 several defects were visible
  only with `-i` on a clean database and invisible with `-u`, because the registry
  came pre-assembled and hid a flaw in its assembly.
- **Run each module's suite on a database with only its dependencies.** A sibling
  that legitimately overrides behaviour will otherwise fail for the right reason
  and hide the wrong one.

---

## Prerequisites and risks

- **The 18.0 branch is alive**: 84 commits in the last 60 days, the most recent
  2026-09-18. Every "byte-identical" claim here has a shelf life.
- **The 18.0 baseline now exists for the modules Batch 1 touched** — see the
  table above. For the rest of Batches 2–4 it still does not: record the numbers
  before changing anything, or a backport regression is indistinguishable from
  something that was already red.
- **Measure on a database that has what the suite actually needs.** `numa_poly`
  reads as 20 red on a database with only `numa_poly` in it, and green once
  `project`, `numa_planning` and `numa_planning_purchase` are there. A baseline
  taken on too small a database is worse than no baseline: it hands you twenty
  failures to chase that were never there.
- **`numa_poly` is load-bearing for the private repository too.** Item 16 of
  `numa-addons-20.0/BACKPORT-18.0.md` (`res.partner` and the polymorphic company
  default) depends on how poly injects fields. Read both documents before
  starting either.
