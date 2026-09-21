# Numa Physical Product — Sale

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Before the migration
**it did not price anything it was written to price**: see
[What was found](#what-was-found-before-migrating).

Sells by the kilo, the metre, the square metre and the cubic metre. A product whose
`price_base` names a physical magnitude is charged for that magnitude, not for the
number of pieces.

## What it adds

On a **sale order line**:

| Field | Meaning |
| --- | --- |
| `unit_width`, `unit_length`, `unit_height`, `unit_surface`, `unit_weight`, `unit_volume` | the product's figures, for reference |
| `total_surface`, `total_weight`, `total_volume` | the line's figures: unit × quantity, and writable, because the piece on the pallet is not always the piece in the catalogue |
| `price_qty` | the quantity the price is applied to |
| `unit_price_uom_id` | what the unit price is per: kg, m, m², m³, or the product's own unit |

On a **sale order**: `so_weight` and `so_volume`, the sums of its lines.

`price_qty` reaches the amounts through
`_prepare_base_line_for_taxes_computation`, the hook Odoo 20's tax engine calls. The
module changes one number in the base line core builds and lets core do the rest —
rounding per document, tax details, global discounts, down payments.

Invoicing carries the magnitude over: `_prepare_invoice_line` passes `price_qty` and
the price unit of measure. For weight and volume the figure is read off the delivered
stock moves, so what is billed is what was actually shipped.

## Dependencies

`numa_physical_product`, `sale`, `sale_stock`.

## What was found before migrating

**The module did not do its job outside the form.** `total_surface`, `total_weight`,
`total_volume` and `price_qty` were plain stored fields, filled only by
`@api.onchange` handlers. An `@api.depends` was stacked on the same methods, which
does nothing: a depends only means something on a field's compute.

So they were filled only when a human typed into the form. A quotation template, an
import, the website shop, an API call, a duplicated order — every one of those
produced a line with `price_qty` at zero. And `price_qty` is what goes on the tax
base: four slabs of 12.5 kg at 3.00/kg were invoiced at **12.00** instead of
**150.00** — a plausible number, on a real invoice, with nothing in the log.

They are computed stored fields now. The totals stay writable, which is the one thing
the onchange allowed.

`unit_price_uom_id` had no compute at all and was only ever set from a method nothing
called, so the price unit of measure on a line was always empty.

**Three overrides pointed at core methods removed in 17.0:**

- `_get_real_price_currency` returned `(0.0, False)`. Had anything still called it,
  every line would have been priced at zero.
- `update_prices` is `_recompute_prices` now, and the `show_update_pricelist` field it
  wrote no longer exists.
- `_get_price_total_and_subtotal_model` is an `account.move.line` method from Odoo 14,
  defined here on a sale order line — so nothing ever called it — computing taxes with
  `compute_all(..., force_sign=...)`, an API the 20.0 engine does not have.

All three are gone. A dead override is how a module comes to look like it is doing
something it stopped doing two versions ago.

The six-way `price_base` branch was also a copy of `product._get_price_qty`, which
`numa_physical_product` centralises for exactly these bridges. It delegates now.

## Tests

```bash
odoo-bin -d <database> -u numa_physical_product_sale --without-demo \
         --test-enable --test-tags=/numa_physical_product_sale --stop-after-init
```

Fifteen tests, where there were none: the line created in code being priced by its
magnitude, each of the seven price bases, unit-of-measure normalisation, the price
unit of measure, a hand-typed total being what is charged and a new quantity
overruling it, the order's totals following a line, tax on the magnitude, what
`_prepare_invoice_line` carries, and that the three dead overrides are gone.

## Author

Gustavo Marino <gamarino@numaes.com>
