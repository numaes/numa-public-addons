# NUMA Product Variant

Extends Odoo's product-variant handling and brings the product configurator to
Purchase Orders.

## Features

### Variant coding and attributes
- `base_code` on product templates; variant `default_code` is built automatically
  from `base_code` plus per-attribute codes (`code_identifier` + `code_value`),
  skipping values equal to an attribute's `default_value`
  (e.g. `WIDGET` + `.CB`).
- Product categories can declare default attributes (`product_attribute_ids`),
  inherited recursively from parent categories and applied on template
  create/category change.
- Attributes with `change_on_create` (length/width/height) set the matching
  variant dimension on creation; variant weight is recomputed from dimensions and
  `weight_factor` (via `numa_physical_product`).

### Product configurator on Purchase Orders
Entering a product template on a purchase order line runs the same
detection/trigger logic as Sales:
- Non-configurable templates auto-assign their single variant (no dialog), both
  in the UI and via a server-side onchange (covers imports/API).
- Configurable templates (multi-value or dynamic attributes) open the reused
  Sales OWL `ProductConfiguratorDialog`, scoped to variant selection/creation.
  The chosen quantity is written to `product_qty`; sale prices are not shown
  (purchase price is recomputed by the purchase line).

## Usage

On a purchase order, add a line and type in the **Product** field (now bound to
the product *template*):

- If the template has a single, non-configurable variant, that variant is
  assigned automatically — nothing else to do.
- If the template is configurable (an attribute has two or more values, or a
  dynamic attribute), the configurator dialog opens. Choose the attribute values
  and quantity, then confirm:
  - if a variant already exists for the chosen combination, it is selected;
  - if the combination is new and the attribute is dynamic, the variant is
    created on the fly (respecting this module's `default_code` / dimension /
    weight logic);
  - the resulting variant is written to the line, and price/description/UoM are
    filled by the standard purchase logic.

Prices shown in Sales' configurator are intentionally hidden here: the purchase
price is computed by the purchase order line (vendor pricelist / last cost), not
by the configurator.

## Design
- `purchase.order.line.product_template_id`: non-stored computed `Many2one`
  (`readonly=False`) mirroring `sale.order.line`; `is_configurable_product` is a
  related boolean used by the widget.
- `_onchange_product_template_id`: reuses
  `product.template.get_single_product_variant()`.
- Controllers `/purchase/product_configurator/{get_values,update_combination,create_product}`
  inherit the Sales controller and neutralize sale pricing via the
  `purchase_configurator` context flag, so `/sale/*` routes are unaffected.
- Frontend: `PurchaseProductConfiguratorDialog` (subclass overriding the 4
  endpoint URLs) + `pol_product_many2one` field widget applied to
  `product_template_id` on the purchase order line view.

## Running the tests

```bash
cd cm-18.0
.venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d <test-db> \
  -u numa_product_variant \
  --test-enable --test-tags /numa_product_variant --stop-after-init
```

Notes:
- `sale` and `purchase` must be installed (they are dependencies).
- If the target database is left inconsistent by unrelated modules, run against a
  fresh test database created with `-i numa_product_variant --without-demo=all`.

## Dependencies
`base`, `product`, `numa_physical_product`, `sale`, `purchase`.

---

# Typed attribute values and record references

## The problem

A `product.attribute.value` can only carry scalar data. That is enough for
"Colour: Red", but not for the two cases this section adds:

- **a value that points at a record** — an attribute whose value *is* a
  `product.template`, a `product.product` or another `product.attribute.value`;
- **a value that is not in any predefined list** — an arbitrary cut length, an
  engraved legend, any record matching a domain.

The driving case is an aluminium joinery workshop. Extruded aluminium is a
`product.template` (the profile type) with variants by strip length, colour and
alloy. A **cut piece** is a separate `product.template` whose attributes are the
profile type, the colour, the alloy, the segment length and the end treatments.
Glass and polycarbonate cut pieces work the same way. The cut piece must resolve
to its base material — but *which* physical strip it is cut from is a
bill-of-materials decision, not a property of the cut piece.

## Two axes Odoo conflates, kept separate here

| Axis | Field | Answers |
|---|---|---|
| Value type | `product.attribute.value_type` | what kind of data does a value carry |
| Materialisation | `product.attribute.create_variant` | does a value produce a variant |
| Presentation | `product.attribute.display_type` | how is the predefined list rendered |

They are orthogonal. A reference attribute can be `always`, `dynamic` or
`no_variant`, and can be rendered as radio buttons or a select.

The predefined values remain an **optional list, not a mode**. An attribute may
have a list *and* accept values outside it — the behaviour SAP calls
*additional values* and D365 models as "Text with or without a fixed list".

## Configuration

On `product.attribute`:

| Field | Meaning |
|---|---|
| `value_type` | `char` (default), `number`, `date`, `reference` |
| `reference_model` | required when `value_type = 'reference'` |
| `reference_domain` | optional domain restricting the referenceable records |
| `allow_additional_values` | accept values outside the predefined list |
| `number_min` / `number_max` | bounds for numeric values |
| `number_rounding` | precision at which two numbers are the same value |
| `code_format` | format string for the generated `code_value` |

The five useful combinations:

| Case | `value_type` | Value list | `allow_additional_values` |
|---|---|---|---|
| Classic attribute | `char` | yes | no |
| Profile type, any template | `reference` | empty | yes |
| Profile type, curated list | `reference` | yes | no |
| Segment length | `number` | standard sizes | yes |
| Engraved legend | `char` | empty | yes |

**`number_rounding` is not cosmetic.** Without it 1250.0 and 1250.0000001 are
two values and therefore two products. For millimetre work, set it to 1.

## Where the reference lives

The payload is provided by the abstract `product.attribute.reference.mixin` and
applied to **both** value models:

- `product.attribute.value` — the reference shared by every template using it;
- `product.template.attribute.value` — an **override** for one template only.

Precedence is resolved in exactly one place, `_get_effective_reference()`.
Consumers must call it rather than reading the columns.

Concrete `Many2one` columns back the reference, with `reference_record` (a
computed `fields.Reference`) as the uniform API. A bare `fields.Reference` would
store `'product.product,42'` as text — no foreign key, no `ondelete`, no way to
filter or join, and deleting a referenced profile would leave silent dangling
pointers.

**Extending it to another model:** add your own `Many2one`, extend
`reference_model` with `selection_add`, and override `_reference_field_map`.

## Materialisation

Odoo ties variant identity to the set of `product.template.attribute.value`
records, so an open value that must produce a product has to become a real
`product.attribute.value`. Everything goes through one entry point:

```python
value = attribute._get_or_create_value({'reference': profile_template})
value = attribute._get_or_create_value({'number': 1250.0})
value = attribute._get_or_create_value({'char': 'Feliz cumpleaños'})
value = attribute._get_or_create_value({'date': '2026-08-12'})

ptav = attribute_line._get_or_create_ptav({'number': 1250.0})
```

This lives on the models, not in a controller: the configurator dialog is not
the only entry path — `_onchange_product_template_id`, imports and direct
`create()` calls reach the same code, and so do the same validations.

### Determinism

The same payload always yields the same value, keyed by `canonical_key`:

| Type | Key |
|---|---|
| reference | the foreign key, not the display name |
| `char` | stripped, **case-sensitive** (`JUAN` and `Juan` are different legends) |
| `number` | rounded to `number_rounding` |
| `date` | ISO string |

`canonical_key` exists because `name` is `translate=True` and therefore a jsonb
column, which can carry neither a unique index nor an exact match.

Two partial unique indexes back this, which is what makes the
savepoint-and-retry in `_get_or_create_value` correct under concurrency: two
simultaneous configurators race on the index and the loser re-reads the winner's
row instead of creating a duplicate.

### Generated codes

`code_value` is generated for materialised values:

- **reference** → the referenced record's `base_code` or `default_code`,
  falling back to a slug of its display name;
- **number** → the attribute's `code_format`, e.g. `%(value)04.0f` → `0800`;
- **text** → an uppercase alphanumeric slug with accents folded.

`build_default_code` is unchanged: it still composes `base_code` plus the
per-attribute `code_identifier` + `code_value`. This is the same composition
Infor LN uses for generated custom item codes — fixed elements plus option
values.

**`default_code` is rebuilt when the combination changes.** A variant does not
only get its values at creation: adding a value to an attribute line that
already has variants makes Odoo attach the new template attribute value to them.
`product.product.write` therefore re-runs `_rebuild_default_code` and
`_apply_attribute_dimensions`, so a variant cannot keep a code from a previous
combination.

### Lines with no predefined values

Core requires at least one value per attribute line, because a line with none
would make the template unconfigurable. That reasoning does not hold for an open
attribute, whose list legitimately starts empty, so `_check_valid_values` is
relaxed for lines whose attribute has `allow_additional_values`.

### Lifecycle

Materialising a master record per free value is something the industrial
configurators deliberately avoid — SAP and D365 keep free values in the instance
valuation. Odoo forces it, so cleanup is a first-class requirement:

- `is_materialized` marks auto-created values; curated ones are never touched by
  any automatic process.
- `ondelete='restrict'`: a profile with cut pieces defined cannot be deleted, and
  the user is told why.
- A daily cron runs `_gc_materialized_values()`, which **archives** — never
  deletes — materialised values with no attribute line and no product usage.
- A materialised value in use by a variant is never archived nor deleted.

## Resolution API

The surface downstream modules consume. Deliberately small and stable:

```python
# product.template.attribute.value
ptav._get_effective_reference()   # applies the PTAV-over-PAV precedence
ptav._get_effective_value()       # typed Python value

# product.product
variant.get_attribute_reference(attribute)     # -> record | empty recordset
variant.get_attribute_references(model=None)   # -> {attribute: record}
variant.find_matching_variants(base_template)  # -> product.product recordset
```

`find_matching_variants` returns the variants of `base_template` sharing this
variant's attribute values. Attributes present on the base but absent here —
strip length, sheet size — are left **unconstrained**, so the result is a
candidate set, not a single variant. It is pure mechanism: it returns
candidates, it does not choose.

The joinery resolution, with no domain-specific code in this module:

```python
base = cut_piece.get_attribute_reference(attr_profile_type)   # product.template
candidates = cut_piece.find_matching_variants(base)           # strips by colour + alloy
```

## Validation

All server-side, because the dialog is not the only entry path.

| Situation | Response |
|---|---|
| Reference outside `reference_domain` | `ValidationError` |
| Reference of the wrong model | `ValidationError` |
| Number outside `[number_min, number_max]` | `ValidationError` |
| Value outside the list with `allow_additional_values = False` | `ValidationError` |
| Empty text | `ValidationError` |
| Cyclic value → value reference chain | `ValidationError` |
| `reference` attribute with no `reference_model` | `ValidationError` |
| `number_min` greater than `number_max` | `ValidationError` |
| Non-positive `number_rounding` on a numeric attribute | `ValidationError` |

## Configurator

The whole configurator speaks in template attribute value ids: `get_values`
returns them, the OWL dialog holds the selected ones, `create_product` receives
them. So the only new endpoint is the one translating an open value into one:

```
POST /sale/product_configurator/resolve_value
POST /purchase/product_configurator/resolve_value
     {product_template_id, ptal_id, payload}
  -> {ptav_id, name, code_value}
```

The frontend injects the returned value into that line, marks it selected and
continues with the standard `update_combination`. Price computation, exclusions,
the variant matrix and `create_product` are untouched.

### OWL

`ProductTemplateAttributeLine` is patched, not forked. It gains an extra control
**beside** the predefined list, never instead of it, so suggestions and free
entry coexist:

| `value_type` | Control |
|---|---|
| `reference` | `Many2XAutocomplete` over `reference_model` + `reference_domain` |
| `number` | numeric input honouring min, max and rounding |
| `char` | text input |
| `date` | date picker |

`display_type` was deliberately **not** extended with `reference` and `free`:
that would re-merge presentation with value source, which is the confusion this
design separates.

The endpoint differs between sales and purchase, so the dialog exposes
`resolveOpenValue` in its sub-environment, reading `this.resolveValueUrl`
lazily — `PurchaseProductConfiguratorDialog` sets it after `super.setup()`.

### Out of scope

`website_sale` and Point of Sale reuse the same OWL components and are **not**
adapted. Open values simply are not offered there. What protects them is that
every validation is server-side.

## Prior art

The design follows the industrial configurators rather than the generalist ones.

| Concept | SAP LO-VC / AVC | Infor LN PCF | D365 SCM PCM | Here |
|---|---|---|---|---|
| Configuration unit | Characteristic (CT04) | Product feature | Attribute | `product.attribute` |
| Value data type | CHAR, NUM, DATE, TIME, CURR, QUAN | Option type | Text / Integer / Decimal / Boolean | `value_type` |
| Predefined values | Allowed values | Options | Text *with or without* a fixed list | `product.attribute.value` |
| Value outside the list | `additional values` flag | — | Integer/Decimal without a range | `allow_additional_values` |
| Reference to a record | Reference characteristic bound to table+field (`MARA-MATNR`) | — | System-defined table constraint | `value_type='reference'` |
| Configured product | KMAT vs material variant | Generic item → generated custom item | Reuse by matching values | `create_variant` |
| Component selection | Object dependencies on the BOM | Constraints by generic item | BOM line maps its product to an attribute | downstream |

## Troubleshooting

**Near-duplicate values keep appearing.** `number_rounding` is finer than the
precision users actually type at. Raise it; existing duplicates can be merged and
the losers archived.

**"X is not an allowed value of attribute Y".** The attribute has
`allow_additional_values = False` and the value is not in its list. Either add it
to the list or open the attribute.

**A product template cannot be deleted.** An attribute value references it
(`ondelete='restrict'`). Find them with
`env['product.attribute.value'].search([('reference_template_id', '=', tmpl.id)])`
and archive the cut pieces first.

**A variant kept an old `default_code`.** Only variants whose template has a
`base_code` are recomposed. Set one on the template.

## Running the tests

```bash
cd cm-18.0
.venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 \
  -u numa_product_variant \
  --test-enable --test-tags /numa_product_variant --stop-after-init \
  --log-level=test
```

Test modules: `test_attribute_typing`, `test_materialization`, `test_codes`,
`test_lifecycle`, `test_resolution_api`, `test_resolve_value_controllers`, plus
the pre-existing `test_numa_product_variant` and the two purchase configurator
suites. The joinery fixture lives in `tests/common.py`.

The OWL layer has no automated coverage — it needs manual verification in the
sales and purchase configurators.
