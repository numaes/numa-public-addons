# Odoo 18 pitfalls that lose data quietly

Six behaviours of Odoo 18 that cost real debugging time, none of them documented
by Odoo, all of them found the same way: a value was wrong in production while
every test was green.

They share a shape. **Odoo does not fail when it cannot honour what you asked
for — it silently does something else.** A quantity becomes 1.0, a computed
field keeps a stale value, a constraint never runs. The code that caused it is
somewhere else, and often in another module.

Recorded 2026-08-12, from building an engineer-to-order configurator over
`product`, `mrp` and `sale`.

---

## 1. A compute without `@api.depends` is cached for the whole transaction

```python
product_width = fields.Float(compute="get_width", inverse="set_width")

def get_width(self):
    for product in self:
        product.product_width = product.variant_width or \
                                product.product_tmpl_id.product_width
```

No `@api.depends`, so Odoo never invalidates it. Whatever it computes first in a
transaction sticks; writing `variant_width` afterwards changes nothing.

**How it showed up.** A variant ended with `variant_width = 0.4` and
`product_width = 0.0` — the two fields of the same pair disagreeing. It had
worked for years because the read normally happens after the write. A loop that
wrote one dimension, read the derived ones, then wrote another exposed it.

**What to do.** Every `compute=` names each field it reads in `@api.depends`. A
compute without one is not "recomputed on demand"; it is computed once. When a
computed value looks stale, check the depends before suspecting the caller.

Corollary: when you write several fields that feed the same derived value, write
them all *first* and recompute once. Recomputing after each write reads a
half-updated record.

---

## 2. `_create_product_variant` returns an existing variant, with its old derived data

Core does the right thing and documents it: if the combination already exists the
variant is returned, and if it was archived it is reactivated. The trap is what
that means for anything you derive.

**How it showed up.** A module built `default_code` and the variant dimensions in
`product.product.create`. Adding a value to an attribute line that already has
variants makes Odoo attach the new template attribute value to them — so the
variant's combination grew, and its code and dimensions stayed as they were. The
product then carried a code describing a configuration it no longer had.

**What to do.** Anything derived from `product_template_attribute_value_ids`
belongs in `write` as well as `create`. Deriving it only at creation is correct
exactly once per variant, and variants outlive their creation.

---

## 3. `@api.constrains` only runs for fields present in the values

Two distinct traps, both silent.

**A create that omits every constrained field is never validated.** Odoo
validates the fields present in the create values. A constraint meant to enforce
"exactly one of these three must be set" never fires on a record that sets none
of them.

*Workaround:* include a always-present required field — usually `name` — in the
trigger list, and say why in a comment.

**Creating a child of a One2many does not revalidate the parent.** A constraint
declared on the parent model never fires when a line is added to it. A
constraint about the relationship therefore belongs on the *child*, checking
upwards.

Both were found the same way: a test asserting `assertRaises(ValidationError)`
passed nothing and failed with "ValidationError not raised".

---

## 4. The product configurator's exclusion map cannot accept new values

`ProductConfiguratorDialog._checkExclusions` indexes the map without a fallback:

```javascript
for (const ptavId of combination) {
    for (const excludedPtavId of exclusions[ptavId]) {   // no || []
```

The map is built by `/sale/product_configurator/get_values` when the dialog
opens. Any template attribute value created **after** that — by any extension
that materialises values on the fly — is absent, and selecting it throws
`TypeError: exclusions[ptavId] is not iterable`.

Note the inconsistency: `parentExclusions[ptavId] || []` two lines below does
guard. Only the main map does not.

**What to do.** After creating a value at runtime, register an empty exclusion
entry for it in the dialog's state before selecting it. A value created just now
excludes nothing, so an empty list is the truthful entry.

---

## 5. `product.attribute.value.name` is translatable, therefore jsonb

`name` is `translate=True`, so the column holds a jsonb document. It cannot carry
a unique index, and it cannot be matched exactly with `=`.

Any scheme that deduplicates attribute values by name — and de-duplicating is
unavoidable the moment values are created on demand — needs its own
non-translatable key column. Discovering this after building the deduplication is
expensive; the field looks like a `Char` everywhere else.

---

## 6. An attribute line must have at least one value

`product.template.attribute.line._check_valid_values` rejects a line with an
empty `value_ids`, because a line with no values would make the template
unconfigurable.

That reasoning does not hold for an attribute whose values are entered freely or
picked from a live catalogue: its list legitimately starts empty and fills up as
values are used. The constraint has to be relaxed for those lines, which means
overriding a core constraint rather than adding one.

---

## Two habits that would have caught all of them sooner

**Assert after a flush.** Computed fields defined by *other* modules can
side-write onto your records, and they only run at flush time. A test that reads
straight after writing validates a state the database never reaches. One suite
here stayed green for months while every quantity it produced was being reset to
1.0 by an installed customer module — and the bug did not reproduce in an
`odoo shell` either, because the shell never flushed between the write and the
read.

```python
self.env.flush_all()
record.invalidate_recordset()
self.assertEqual(record.field, expected)
```

**Drive the UI in a browser.** Server-side tests prove nothing about OWL. Write
an Odoo tour and run it with `start_tour`: it uses the real web client and the
real asset bundle. Two defects here survived 161 passing tests — a control that
rendered without its label, and pitfall 4 above, which broke the feature on the
first real interaction.

When a tour fails, **open the screenshot Odoo saves** under
`/tmp/odoo_tests/<db>/screenshots/` before theorising. It is faster and more
truthful than reading selectors, and it will also tell you things you did not ask
— that the database runs in another language, or that the customer has replaced
half the form.

---

## The pattern worth remembering

Every one of these is Odoo choosing to continue rather than to fail. That is a
defensible choice for a framework that must survive partial data, and it is a
hazard for anything that computes a physical quantity or a price.

Where your own code cannot honour what the caller asked for, **raise**. A bill of
materials missing a component, or carrying a quantity nobody asked for, gets
manufactured and costed. Being silent turns a visible error into a wrong
physical product.
