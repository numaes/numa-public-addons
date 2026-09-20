# Relative date filters in Odoo 20

How to build a date filter that, saved as a favourite, **keeps moving with today's date**
instead of freezing on the day it was created.

The feature is native. This document exists because the editor does not say what the range
is anchored on, and because what Odoo offers here changed substantially between 18.0 and
20.0.

---

## The problem

The intuitive move is to type the date with a shortcut. In a date field Odoo accepts
`+2w`, `-3m`, `+10d`: you type it and the widget fills in the resulting date.

That does **not** produce a relative filter. The shortcut is resolved by the date widget as
you type: the domain receives the literal date. When the favourite is saved, what is stored
is `2026-09-17`, not "two weeks from today". A week later the filter still points at the
same fixed day.

The same is true — and this is less obvious — of the **period filters in the search bar**
("This month", "Last quarter", "This year"). They look relative and are not: they are
computed as concrete dates against the reference date of the moment
(`web/static/src/search/utils/dates.js`, `constructDateRange`). Saved as a favourite they
are just as fixed.

Relativity is not in **how the value is written**. It is in **the operator**.

---

## How to do it

1. In the list or kanban view, open **Filters → Add Custom Filter**.
2. Pick the date field (for example *Created on*).
3. Choose the operator **`is in range`**.
4. A value-type selector appears. Odoo 20 offers named presets — *Last month*, *Year to
   date*, *Last 365 days* — and two free-form entries:
   - **Date range**: two concrete dates. Not relative.
   - **Relative range**: an amount and a unit, counted from today. **Only visible in
     developer mode** (`tree_editor_components.js:106` marks it `debugOnly`).
5. With **Relative range**, load for example `-1` and `months`.
   - **Negative** = backwards. `-1 months` is "from a month ago until today".
   - **Positive** = forwards. `+7 days` is "from today until a week from now".
6. **Add**, then save it with **Save current search** and a name.

With this module installed, a `from today` label appears next to the boxes, with a tooltip
recalling that the filter is recalculated on every use. It is only a label: the behaviour is
the same with or without the module.

The named presets are relative too, and their names say so. The free-form editor is the one
that says nothing, which is where the label goes.

---

## What gets stored, and why it works

The relative range does not generate dates: it generates **smart date** expressions. For
`-1 months` on a `date` field, what is stored is:

```python
[
    "&",
    ("create_date", ">=", "today -1m"),
    ("create_date", "<=", "today"),
]
```

Three pieces make that survive:

1. **The favourite is serialised without being evaluated.** On save, the search model asks
   for the raw domain: `this._getDomain({ raw: true, withGlobal: false }).toString()`
   (`web/static/src/search/search_model.js:2430`). With `raw: true` it returns the tree as
   it is, expressions intact.
2. **`ir.filters.domain` is a Text field**, not an evaluated structure. It stores the string.
3. **It is re-evaluated on every use.**

The filter moves on its own because there never was a stored date.

The reverse path works too: edit the filter later and Odoo recognises those expressions and
shows it again as a range with its amount and unit. It does not degrade into a raw domain.

---

## What changed in Odoo 20

### The `within` operator is gone

Up to 18.0 the relative filter was a dedicated operator, `is within`, whose editor was the
template `web.TreeEditor.Within`. Odoo 20 replaced it with `is in range` plus a value type,
and the editor is `web.TreeEditor.relativeRange` (`tree_editor_components.js:60`).

### Relative dates now evaluate server side

This is the substantial change. Up to 18.0 the generated domain was made of Python
expressions — `(context_today() + relativedelta(months=-1)).strftime("%Y-%m-%d")` — which
only the client could evaluate: `ir.filters._get_eval_domain` exposed `datetime` and
`context_today` but **not** `relativedelta`, so a saved relative filter did not evaluate
from Python.

Odoo 20 generates smart dates instead (`today -1m`) and the **ORM parses them itself**,
through `odoo/tools/date_utils.py:parse_date`, which `odoo/orm/domains.py` calls when
comparing a date field. The DSL is documented in that function and is wider than what the
editor offers: `d`, `w`, `m`, `y`, `H`, `M`, `S`, plus anchors such as `=1d` (first day of
the month), `=6m` (June), `=tuesday`, `=week_start`.

So a relative domain written by hand now works from Python as well as from the client.

### Named presets

*Last month*, *Year to date*, *Last 365 days* and the rest are generated as smart dates too,
so they stay relative when saved. They did not exist in 18.0, and they are what most users
will reach for.

---

## Limits of the editor

These are limits of the **editor**, not of the domain: anything the DSL above expresses can
be written by hand into `ir.filters.domain`.

1. **Four units.** Days, weeks, months and years. No hours, minutes or quarters in the
   value editor, even though `parse_date` understands `H`, `M` and `S`.
2. **Always a range anchored on today.** A single relative bound — "older than two weeks",
   with no floor — cannot be expressed from the editor.
3. **The anchor is always today.** No "first day of the current month" from the editor,
   although `=1d` does exactly that in the DSL.

---

## Core files involved

For when this has to be reviewed in a later version:

| File | What it contributes |
|---|---|
| `core/tree_editor/virtual_operators.js` | `makeRelativeBetween`, the smart-date generation and the `between` / `relativeBetween` recognition |
| `core/tree_editor/tree_editor_components.js` | the `relativeRange` component, the value-type list and its `debugOnly` flag |
| `core/tree_editor/tree_editor_components.xml` | the templates, including the one this module inherits |
| `search/search_model.js` | saves the favourite with `raw: true` |
| `search/utils/dates.js` | the period filters, which do compute concrete dates |
| `odoo/tools/date_utils.py` | `parse_date`: the server-side smart date DSL |
