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
