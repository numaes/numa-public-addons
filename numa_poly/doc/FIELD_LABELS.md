# Why a polymorphic model's fields came out in English

## The symptom

A `project.task` form showed all 38 propagated planning fields — effort,
constraint type, total float — in English, while the very same fields on
`numa.planning.node` read in Spanish. The dropdown of a propagated selection
was English too. Every `.po` file involved was complete and correct, and
loaded: `numa_planning` parsed 362 translated entries, and the node's own
labels were translated in the database.

It looks like a translation that will not load. It is a translation with
nowhere to land.

## The cause

A translatable label is not stored in the `.po`. The `.po` is loaded once and
written into the database, keyed by the record it belongs to — for a field
label, an `ir.model.fields` row, named in the file as

```
#: model:ir.model.fields,field_description:numa_planning.field_numa_planning_node__pln_effort_hours
```

A polymorphic dependent gets an `ir.model.fields` row **of its own** for every
propagated field: `project.task.pln_effort_hours` is a different row from
`numa.planning.node.pln_effort_hours`. No `.po` names it — it does not exist
until the registry builds it, and it belongs to no module's export — so it
keeps the label the field definition carried, which is the source language.

This is not specific to planning. It affects every propagated field of every
polymorphic pair, which on a populated database is hundreds of labels.

## The fix

`ir.poly_base._poly_sync_dependent_field_labels()` copies the base row's
`field_description` and `help` — the whole jsonb, so every language at once —
onto the dependent's row, and does the same for selection option labels in
`ir_model_fields_selection`.

It only touches a clone **still carrying the base's own source label**, so a
dependent that deliberately renames or re-documents a field keeps what it
said.

Two shapes in the graph need care:

- A **diamond** — `conversation.message` has two bases — would be claimed by
  both in turn, and the two would overwrite each other's translations on every
  pass. The first base in a stable order owns a name; the others skip it.
- A **chain**, where a dependent is itself a base, needs the sweep run again:
  a pass may reach the far end before the near one. It converges in as many
  passes as the chain is deep and stops as soon as a pass writes nothing.

It runs from `_cron_poly_backfill_pending`, for the reason that cron exists: a
registry that is finished and usable, and a mechanism that repairs itself
without anybody having to remember to run it. It is idempotent and writes only
what is still in the source language, so a tick with nothing to do costs
nothing.

## Running it by hand

```python
env['ir.poly_base']._poly_sync_dependent_field_labels()
```

On a database with the planning bridges installed this adopted 666 labels the
first time.

## Diagnosing the next one

Do not start from the `.po`. Compare the two rows:

```python
F = env['ir.model.fields']
for model in ('numa.planning.node', 'project.task'):
    f = F.search([('model', '=', model), ('name', '=', 'pln_effort_hours')])
    print(model, f.with_context(lang='es_AR').field_description)
```

If the base reads in the user's language and the dependent does not, this is
that bug. If neither does, the `.po` really did not load — and in Odoo 18 the
usual reason for *that* is a hand-written file: an entry is read as a Python
translation only when it carries the `#. odoo-python` marker, so a file
written by hand parses to zero entries while looking perfectly correct.
Export the template with `--i18n-export` and fill it in.
