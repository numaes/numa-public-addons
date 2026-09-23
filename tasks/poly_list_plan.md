# poly_list and numa_polimorphic_widget — make them work

Date: 2026-09-23 · Branch: 20.0 · Module: numa_poly (fixtures in numa_poly_test)

## What they are for (USER_GUIDE.md)

- `js_class="poly_list"` on a standalone list of a polymorphic base model:
  - opening a row shows the **concrete** model's form;
  - "New" asks which subtype, then opens that subtype's form.
- `widget="numa_polimorphic_widget"` on a one2many/many2many of a polymorphic base
  model, inside a form:
  - "Add" asks which subtype and opens its form in a dialog;
  - what the user enters travels as `poly_payload` (JSON) on a virtual line;
  - saving the parent creates the concrete record. The backend already does this: a
    base-model create with `concrete_model_id` + `poly_payload` is dispatched to the
    concrete model;
  - opening a saved line shows the concrete form.

## Why it never worked (read, 2026-09-23)

- `useService("rpc")`: the service has been gone since 17, so the renderer failed in
  setup.
- `concrete_model_id` was read as `[id, name]`, the pre-17 shape; it is `{id, display_name}`.
- "Add" created an empty virtual line *and* opened an unrelated concrete form, so what
  the user typed was either lost or saved as a separate record. The code says so
  itself ("For a production implementation, you may want to...").
- The subtype dialog template calls `this._t`, which does not exist.
- `get_poly_subclasses_info()` returns `[]` unless each model overrides it, so with
  no override "New"/"Add" never asked anything.
- Reading `ir.model` from the client needs rights that ordinary users lack.

## Design

Backend (numa_poly):
- `get_poly_subclasses_info()` defaults to the concrete models registered under the
  base in the poly hierarchy; an override still wins.
- `poly_ui_subclasses()`: the subtypes plus their `ir.model` ids (sudo), which the
  create path needs as `concrete_model_id`.
- `poly_ui_concrete_models(ids)`: `{id: model}` for the given records (sudo on
  `ir.poly_base`).

Frontend (numa_poly):
- `poly_ui.js`: the subtype dialog and the two RPC helpers.
- `poly_list` view: a ListController override.
  - `openRecord` opens the concrete model's form (current window, with a breadcrumb);
  - `createRecord` asks the subtype, then opens its form for a new record.
- `numa_polimorphic_widget`: an X2ManyField override.
  - `onAdd`: ask the subtype, then open a FormViewDialog on the concrete model. Its
    `onRecordSave` checks validity, takes the changes, and adds a virtual line with
    `concrete_model_id` and `poly_payload` (plus the base fields the list shows). The
    concrete record is created when the parent is saved.
  - `openRecord`: a saved line opens the concrete form in a dialog, and the line
    reloads after saving. An unsaved virtual line reopens its form prefilled with the
    payload, and saving updates the payload.
- The empty `PolyListRenderer` template inheritance goes.

Fixtures (numa_poly_test): `test.poly.site` with `item_ids` (one2many to `test.test1`,
whose subtypes are `test.test2` and `test.test3`); a site form using the widget; a
`test.test1` list with `js_class="poly_list"`; actions and access.

## Verification

- [x] Tours, red first on the current code:
  - standalone list: open a Test2 row, see its own field `a3`; New → pick Test3 →
    Test3 form;
  - x2many: Add → pick Test3 → fill `a1`/`a4` → the line shows `a1` → save the site →
    the server has a `test.test3` with `a4` under the site; open the saved line, edit
    `a4`, save → persisted.
- [x] Python tests for the three backend methods.
- [x] numa_poly and numa_poly_test suites in the three setups (alone, with fixtures,
  full).
- [x] Screenshots of the site form, the subtype dialog and the list (the concrete
  form is exercised by the tours).

## Review (2026-09-23)

Both work, verified in a browser: the tours were red on the old code (the list failed
with "Missing template", the widget with "Invalid component props") and are green now,
with the server-side results asserted.

The design held; making it work found five defects beyond the JS:
1. **Hierarchy roots had no `concrete_model_id` / `poly_payload`.** ir.poly_base gives
   them to subtypes only, so a root's list could not show the type and a new line had
   no way to carry its payload. They are now contributed to each root as non-stored
   fields, the same way poly declares a subtype's bases.
2. **A root's create ignored the payload.** The payload was only read in the
   polymorphic branch, and a root is not "polymorphic" there. With the new field it
   would have been accepted and silently dropped. Roots now dispatch each row to its
   subtype (`_poly_create_through_root`).
3. **A batch mixing subtypes went entirely to the last row's subtype.** A parent saved
   with a Test2 line and a Test3 line created both as Test3. Each row now goes to its
   own subtype.
4. **`concrete_model_id` was required on subtypes** (it comes from ir.poly_base), and it
   is read-only there. Any form showing it, Odoo's generated one included, could not be
   saved. It is now declared not required on the contributed definition. The
   post-setup pass that tried to do this never reached `fields_get`.
5. **`get_poly_subclasses_info()` returned `[]`** unless overridden, so nothing was ever
   offered. It now defaults to the registered hierarchy.

Also: payload keys starting with `__` are client annotations and are ignored; the
payload's `concrete_model_id` is read after the merge.

Numbers:
- numa_poly alone: 139.
- With numa_poly_test: 255 (11 new).
- Full setup (planning bridges, Twilio, es_AR), numa_poly, numa_poly_test, planning ×4
  and conversation ×2: 520, 0 failed. The 25 skipped need OR-Tools or conversation.bot.

The full setup also exposed five tests that assumed an English user, all written
earlier: the two conversation tab tests, two planning message tests, and my own widget
tour. They now select by name or pin `lang=en_US`.

Found, not ours: on Odoo 20, `-u` of a module that loads before website and inserts a
new view fails on website's NOT NULL `ir_ui_view.visibility`. Reproduced on a vanilla
database (website + `-u contacts` after deleting one of its views), so it is core
behaviour.

Flagged, not changed: `PolyBase._setup_base` and `_build_poly_fields` are never called
in Odoo 20 (model setup goes through `model_classes._setup`; poly's fields arrive via
`_poly_contribute_definitions`). They are dead code worth removing in a separate change.
