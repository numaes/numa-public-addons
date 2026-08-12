# Typed Attribute Values and Record References — `numa_product_variant`

**Date:** 2026-08-12
**Module:** `numa_product_variant` (numa-public-addons-18.0)
**Status:** Approved design, pending implementation plan

## Problem

`product.attribute.value` can only carry scalar data. `numa_product_variant` adds
`code_value`, `value_on_create` and `weight_factor`, but an attribute value
cannot point at another record.

Three capabilities are missing:

1. An attribute value that **references a record** — `product.template`,
   `product.product` or another `product.attribute.value`.
2. An attribute whose values are **not restricted to a curated list**: the user
   picks any record matching a domain, or types a free value (an engraved
   legend, an arbitrary cut length).
3. The product configurator (sales and purchase) supporting both generically.

The driving case is an aluminium joinery workshop. Extruded aluminium is a
`product.template` (the profile type) with variants by strip length, colour and
alloy. A **cut piece** is a separate `product.template` whose attributes are the
profile type, the colour, the alloy, the segment length and the left/right end
treatments (90°, 45°, 30°, -45°, -30°). Glass and polycarbonate cut pieces work
the same way: base sheet type plus width and height.

The cut piece must resolve to its base material. Which physical strip or sheet
the piece is cut from is **explicitly out of scope**: a 80 cm piece is
indifferent to whether it comes from a 6 m or a 4.5 m strip. That selection
belongs to a downstream bill-of-materials wizard.

This module must provide the **generic mechanism**. The joinery case is one
consumer; other modules will use record references for other resolution cases.

## Scope

**In scope**

- Type declaration on `product.attribute`.
- Reference and free-value payload on `product.attribute.value`, overridable on
  `product.template.attribute.value`.
- On-demand materialisation of attribute values, with deterministic
  deduplication and a lifecycle policy.
- Automatic `code_value` generation for materialised values.
- A small public API for downstream modules.
- Sales and purchase configurator support (the purchase configurator already
  lives in this module).

**Out of scope**

- Choosing which physical strip or sheet a cut piece comes from.
- Consumption and offcut calculation from cut angles.
- Costing, BOM generation and cut optimisation.
- The joinery vertical module itself.
- `website_sale` and Point of Sale configurators. They reuse the same OWL
  components but will not be adapted. Server-side validation protects them: open
  values are simply not offered there.
- Configurable code composition (`code_template` on `product.template`). Noted as
  future work; see "Future work".

## Prior art

The design follows the industrial configurators rather than the generalist ones.

| Concept | SAP LO-VC / AVC | Infor LN PCF | D365 SCM PCM | This design |
|---|---|---|---|---|
| Configuration unit | Characteristic (CT04) | Product feature | Attribute | `product.attribute` |
| Value data type | CHAR, NUM, DATE, TIME, CURR, QUAN | Option type | Text / Integer / Decimal / Boolean | `value_type` |
| Predefined values | Allowed values | Options | Text *with or without* a fixed list | `product.attribute.value` |
| Value outside the list | `additional values` flag | — | Integer/Decimal without a range | `allow_additional_values` |
| Reference to a record | Reference characteristic bound to table+field (e.g. `MARA-MATNR`) | — | System-defined table constraint mapping an attribute type to a table field | `value_type='reference'` + `reference_model` |
| Configured product | KMAT (no master) vs material variant (real, stockable master) | Generic item → generated custom item | Reuse by matching attribute values | Odoo's `create_variant` |
| Component selection | Object dependencies on the BOM | Constraints by generic item | BOM line maps its product to an attribute | Out of scope, downstream |

Three conclusions drove the design:

1. **A value source is not a mode.** SAP models a data type plus an optional
   allowed-value list plus an `additional values` flag; D365 models "Text with or
   without a fixed list". Neither treats "list" and "free" as mutually exclusive.
   A list of suggested values that also accepts other values is a common and
   necessary case.
2. **The type is declared on the attribute, and references resolve against live
   data.** SAP reference characteristics and D365 system-defined table
   constraints both bind the attribute to a table, so the allowed values *are*
   the table. Materialised values are an identity cache, not the source of truth.
3. **No industrial configurator materialises a master value record per free
   value.** They store the value in the instance valuation. Odoo forces
   materialisation because variant identity *is* the set of
   `product.template.attribute.value` records. This design therefore treats the
   lifecycle of materialised values as a first-class requirement rather than an
   afterthought.

Infor LN's generated custom item code — fixed code elements plus option values —
is exactly the existing `base_code` + `code_identifier` + `code_value`
composition, which is why the graft stays small.

## Architecture

### Attribute declares the type

```python
class ProductAttribute(models.Model):
    _inherit = 'product.attribute'

    value_type = fields.Selection([
        ('char', 'Text'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('reference', 'Reference to a record'),
    ], default='char', required=True)

    reference_model = fields.Selection(...)     # when value_type == 'reference'
    reference_domain = fields.Char()            # optional, evaluated server-side

    allow_additional_values = fields.Boolean()  # SAP's "additional values"
    number_min = fields.Float()
    number_max = fields.Float()
    number_rounding = fields.Float(default=0.001)

    code_format = fields.Char()                 # code_value format for materialised values
```

On `product.attribute` these fields **declare** the type. On the value models
(below) `reference_model` reappears as the stored **discriminator** of which
concrete column holds the payload.

`value_type` is orthogonal to `create_variant` and to `display_type`. Variant
materialisation keeps using Odoo's existing `create_variant` axis
(`always` / `dynamic` / `no_variant`), which is the counterpart of SAP's
configurable material versus material variant decision. No new field for it.

Predefined values remain ordinary `product.attribute.value` records: an
**optional list**, not a mode. An attribute may have a list *and* accept values
outside it.

| Case | `value_type` | Value list | `allow_additional_values` |
|---|---|---|---|
| Classic attribute | `char` | yes | no |
| Profile type, open to any template | `reference` | empty | yes |
| Profile type, predefined list | `reference` | yes | no |
| Segment length | `number` | standard sizes | yes |
| Engraved legend | `char` | empty | yes |

### Payload mixin, applied to both value models

The reference lives on `product.attribute.value` and is overridable on
`product.template.attribute.value`, so the payload is identical on both models.
An abstract mixin avoids duplicating it:

```python
class ProductAttributeReferenceMixin(models.AbstractModel):
    _name = 'product.attribute.reference.mixin'
    _description = 'Typed attribute value payload'

    reference_model = fields.Selection(...)          # discriminator
    reference_template_id = fields.Many2one('product.template', ondelete='restrict')
    reference_variant_id = fields.Many2one('product.product', ondelete='restrict')
    reference_value_id = fields.Many2one('product.attribute.value', ondelete='restrict')

    reference_record = fields.Reference(..., compute=..., inverse=...)

    is_materialized = fields.Boolean()
    free_number = fields.Float()
    free_date = fields.Date()
    # The canonical text of a free value lives in the existing `name` field.
```

Concrete `Many2one` columns rather than a bare `fields.Reference`:
`Reference` stores `'product.product,42'` as text, with no foreign key, no
`ondelete` and no way to filter or join. Deleting a referenced profile would
leave silent dangling pointers. Concrete columns give real referential
integrity, and make "every cut piece using this profile" a searchable query. The
computed `reference_record` provides the uniform generic API, and another module
can add its own model by adding a `Many2one` and extending the `Selection`,
staying extensible without losing integrity.

On `product.template.attribute.value` the mixin fields default to `False` and
**only override** the `product.attribute.value` when set. Precedence is resolved
in exactly one place, `_get_effective_reference()`, so no consumer needs to know
the rule.

### Uniqueness

Partial unique indexes per attribute, required for deterministic
materialisation:

- reference: `(attribute_id, reference_model, reference_<model>_id)`
- free value: `(attribute_id, name)` over `is_materialized` records

## Materialisation

### Single entry point

```python
product.attribute._get_or_create_value(payload)               -> product.attribute.value
product.template.attribute.line._get_or_create_ptav(payload)  -> product.template.attribute.value
```

`payload` is a normalised dict: `{'reference': ('product.template', 42)}`,
`{'number': 1250.0}`, `{'char': 'Feliz cumpleaños'}`. The second method also adds
the value to the line's `value_ids` when missing, which is the precondition for
Odoo to create the dynamic variant.

This logic lives on the models, not in the controller. The configurator dialog is
not the only entry path: `_onchange_product_template_id` (already in this
module), imports and direct `create()` calls must all reach the same code.

### Canonical key

- **reference** → `(attribute_id, reference_model, reference_<model>_id)`
- **char** → `(attribute_id, name)` with `strip()`, case-sensitive (`JUAN` and
  `Juan` are different legends)
- **number** → `float_round(value, precision_rounding=attribute.number_rounding)`

`number_rounding` is not cosmetic. Without it, 1250.0 and 1250.0000001 are two
distinct values and therefore two distinct products. The joinery case should set
it to 1 mm.

### Concurrency

Two users configuring the same value simultaneously collide on the unique index.
Handled with the standard pattern: `savepoint`, catch `UniqueViolation`,
re-query, continue. With `create_variant='dynamic'` this is a matter of time, not
an edge case.

### Code generation

`code_value` is `required=True`, so materialised values must generate one. An
overridable hook per attribute:

```python
product.attribute._build_code_value(payload) -> str
```

- **reference** → the referenced record's `base_code` / `default_code`; falling
  back to a slug of its `display_name`
- **number** → `code_format` (Char, e.g. `%(value)04.0f` → `1250`)
- **char** → uppercase alphanumeric slug, truncated

`build_default_code` is **not modified**. It keeps concatenating
`code_identifier` + `code_value` as today.

### Lifecycle

Because this materialises what SAP and D365 deliberately do not, cleanup is a
requirement:

- `is_materialized` marks auto-created values; hand-curated values are never
  touched by any automatic process.
- `ondelete='restrict'` on references: a profile with cut pieces defined cannot
  be deleted, and the user is told why.
- `_gc_materialized_values()` (cron) **archives**, never deletes, materialised
  values with no attribute line and no product usage. It relies on the core
  `is_used_on_products` computed field.
- A materialised value in use by an existing variant is never archived nor
  deleted.

## Public API

Deliberately small and stable:

```python
# product.template.attribute.value
_get_effective_reference()             # applies PTAV > PAV precedence
_get_effective_value()                 # typed Python value

# product.product
get_attribute_reference(attribute)     -> record | False
get_attribute_references(model=None)   -> {attribute: record}
find_matching_variants(base_template)  -> product.product recordset
```

`find_matching_variants` returns the variants of `base_template` sharing the same
`product.attribute.value` records. Attributes present on the base template but
absent from the configured product — strip length, sheet size — are left
**unconstrained**, so the result is a candidate set rather than a single variant.
It is pure mechanism with no business policy: it returns candidates, it does not
choose. The downstream bill-of-materials
wizard decides, the same way a D365 BOM line resolves its component while nesting
remains a separate concern.

The joinery resolution then needs no domain-specific code in this module:

```python
base = cut_piece.get_attribute_reference(attr_profile_type)   # product.template
candidates = cut_piece.find_matching_variants(base)           # strips by colour + alloy
```

## Validation

All server-side. The configurator is not the only entry path.

| Situation | Response |
|---|---|
| Reference outside `reference_domain` | `ValidationError` |
| Number outside `[number_min, number_max]` | `ValidationError` |
| Value outside the list with `allow_additional_values=False` | `ValidationError` |
| Cyclic `product.attribute.value` → `product.attribute.value` chain | `ValidationError` |
| Referenced record archived | readable, blocked when configuring |

## Configurator

The whole configurator speaks in PTAV ids: `get_values` returns attribute lines
with their PTAVs, the OWL dialog holds `selected_attribute_value_ids`, and
`create_product` receives `ptav_ids`. So the only new endpoint is the one that
translates an open value into a PTAV:

```
POST /sale/product_configurator/resolve_value
     {product_template_id, ptal_id, payload}
  -> {ptav_id, name, code_value}
```

The frontend injects the returned PTAV into that line's `attribute_values`, marks
it selected, and continues with the standard `update_combination`.
`create_product`, price computation, exclusions and the variant matrix are
untouched.

Purchase orders are already covered inside this module:
`PurchaseProductConfiguratorController` adds
`/purchase/product_configurator/resolve_value` delegating to the sales
implementation, the same pattern as the three existing routes. No other module in
the `cm-18.0` addons path reuses the configurator, so nothing else needs
adapting.

### OWL component

`ProductTemplateAttributeLine` validates `display_type` against a closed list in
its props. Extending that list with `'reference'` and `'free'` would be wrong: it
would re-merge presentation with value source, which is precisely the confusion
this design separates.

Instead, two new props (`value_type`, `allow_additional_values`) and an extra
control **beside** the list, not replacing it:

| `value_type` | Extra control |
|---|---|
| `reference` | autocomplete over `reference_model` + `reference_domain` (`Many2XAutocomplete`) |
| `number` | numeric input with min/max and the attribute rounding |
| `char` | text input |
| `date` | date picker |

The predefined list keeps rendering through its `display_type` as always. The
extra control appears when `allow_additional_values` is set or the list is empty
— exactly SAP's *additional values* behaviour, where the list and free entry
coexist. Implemented with `patch()` on the existing component, without forking
it.

## Backward compatibility

With `value_type='char'`, a populated value list and
`allow_additional_values=False`, behaviour is identical to today. All new columns
are nullable, `code_value` stays `required`, and `build_default_code` does not
change. Existing attributes need no migration.

## Testing

Built on the module's existing `tests/common.py` `TransactionCase` fixtures, plus
a joinery fixture: a *Profile* template with colour, alloy and strip length, and
a *Cut piece* template sharing colour and alloy.

- **Determinism** — the same payload twice returns the same value; rounding
  (1250.0 versus 1250.0001); case sensitivity for text
- **Codes** — generation for all types; no regression in `build_default_code` for
  list attributes
- **Constraints** — domain, min/max, `allow_additional_values=False`, value cycle
- **Concurrency** — force the `UniqueViolation` and verify the savepoint-and-retry
  path returns the existing value
- **Lifecycle** — the GC archives unused values and refuses used ones;
  `ondelete='restrict'` when deleting a referenced profile
- **API** — `get_attribute_reference` and `find_matching_variants` over the
  fixture
- **Integration** — full `resolve_value` → `create_product` flow, in sales and in
  purchase, following `tests/test_purchase_configurator_controllers.py`

Run against a clean database:

```bash
cd cm-18.0
.venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d <fresh-db> \
  -i numa_product_variant --without-demo=all \
  --test-enable --test-tags /numa_product_variant --stop-after-init
```

## Delivery

**Phase 1 — server-side.** Attribute type declaration, payload mixin,
materialisation, code generation, lifecycle, public API, validations, tests.
Usable on its own through the API and imports, and verifiable without any UI.

**Phase 2 — configurator.** `resolve_value` endpoint for sales and purchase, OWL
component extension, integration tests.

## Future work

- **Configurable code composition.** Infor LN's *Settings for Data Generation*
  declares the item code as fixed elements plus option values, configurable per
  generic item. This module hardcodes `base_code + '.' + concat(code_identifier +
  code_value)`. A `code_template` field on `product.template`, defaulting to
  today's behaviour, would align with that. Deliberately excluded here to keep
  the scope on the typing and materialisation mechanism.
- **Joinery vertical module.** Consumption and offcut calculation from cut
  angles, bill-of-materials wizard, cut optimisation. `cm-addons-18.0` has no
  profile or cut-piece modelling yet, and `cm_products` does not depend on
  `numa_product_variant`; that dependency will need adding.
- **`website_sale` and POS configurators**, if open values are ever needed on
  those channels.
