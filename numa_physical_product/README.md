# NUMA Physical Product

Physical magnitudes on products — width, height, length, surface, volume and
weight — plus the price and cost scaling that makes cut-to-size work.

## Why it exists

A profile is bought by the bar and consumed by the metre; a sheet is bought by
the unit and consumed by the square metre. `price_base` states which magnitude a
product is priced and costed by, and `_get_price_qty` is the single place that
turns a quantity of units into a quantity of that magnitude.

```python
product._get_price_qty(3.0)        # 3 bars of 6 m, priced by length -> 18.0
```

`numa_physical_product_{sale,purchase,invoice}` use it on documents, and
`numa_dynamic_bom` uses it to cost a BOM line, which is what lets one bill say
*0.8 m of profile* and cost it correctly.

## Derived magnitudes

Surface, volume and weight follow from the dimensions:

| Magnitude | Derived from |
|---|---|
| `surface` | `product_length * product_width` |
| `volume` | `product_length * product_width * product_height` |
| `weight` | `weight_factor` × the magnitude named by `weight_kind` |

`weight_kind = 'normal'` means the weight is not derived at all: it was entered
by hand and nothing overwrites it.

The derivation runs on **every write path** — `create`, `write` and the form —
and the onchange delegates to the same code, so the ORM and the form cannot
disagree. This matters because products are created by imports, data files and
configurators far more often than by hand; while the derivation was an
`@api.onchange` alone, a configured sheet reached the database with a surface of
zero and was costed at zero per square metre.

Three rules hold everywhere:

- **A stated value is never overruled by a derived one.** Passing `surface`
  explicitly keeps that surface. The derivation fills in what the caller left
  out; it does not correct what the caller said.
- **Nothing is derived unless something it depends on was written.** A write
  that touches no dimension leaves the magnitudes alone.
- **Nothing is derived from dimensions that are not there.** A product carrying
  no dimensions keeps its hand-entered surface, and no weight is derived from a
  magnitude of zero — a zero derived from an empty dimension states nothing, and
  on a single-variant template Odoo would propagate it down and erase the weight
  the variant derived from its own dimensions.

## Template and variant

Both levels carry the magnitudes. On a variant they are stored in `variant_*`
columns and read through a compute that **falls back to the template when the
variant's own value is zero**, so a variant only overrides what it actually
states.

A variant therefore derives into its own columns only when it carries at least
one dimension of its own; one that carries none keeps inheriting, and keeps
following the template when the template's dimensions move.

> **Known limitation.** Because zero means *inherit*, a genuine zero cannot be
> expressed on a variant. This is a real modelling defect, recorded in
> `numa-addons-18.0/docs/superpowers/specs/2026-09-09-configure-to-order-pipeline.md`.

### Extending the derived weight

`product.product._physical_weight_multiplier()` scales a derived variant weight
by one. `numa_product_variant` overrides it so an attribute value — an alloy, a
wall thickness — can carry a `weight_factor` of its own. Override that hook
rather than reimplementing the derivation: a second copy of it is exactly how
the form and the configurator came to produce different weights for the same
variant.

## Pricelists

`product.pricelist.item.base` gains `length`, `width`, `height`, `surface`,
`volume` and `weight`, so a price can be stated per metre, per m² or per kg.

## Units

Every magnitude is in SI and hardcoded: metres, m², m³, kilograms. Precision
comes from the `Stock Length`, `Stock Surface` and `Stock Volume` decimal
precisions, three digits each. There is no per-product unit of measure for
dimensions, and a numeric product attribute carries no unit either — a
configurator asking for millimetres must convert before the value reaches
`change_on_create`.

## Dependencies

`base`, `product`, `stock`, `stock_account`, `purchase_stock`.

## Running the tests

```bash
cd /home/gamarino/odoo/cm-18.0
.venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 \
  -u numa_physical_product --test-enable --test-tags /numa_physical_product \
  --stop-after-init --log-level=test
```
