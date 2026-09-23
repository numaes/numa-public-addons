# Numa Physical Product — Sale

**Odoo 18.0** | LGPL-3 | NUMA Extreme Systems

Module version `18.0.0.2`. Up to `18.0.0.1` **it priced physical magnitudes only when
a human typed into the form, and even then only on the line, not on the order**: see
[What was found](#what-was-found-in-18001).

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

`price_qty` reaches the amounts through `_prepare_base_line_for_taxes_computation`,
the hook the 18.0 tax engine calls for the line, the order totals and the down payment
wizard alike. The module changes one number in the base line core builds and lets
core do the rest.

Invoicing carries the magnitude over: `_prepare_invoice_line` passes `price_qty` and
the price unit of measure. For weight and volume the figure is read off the delivered
stock moves, so what is billed is what was actually shipped.

## Dependencies

`numa_physical_product`, `uom`, `sale_management`.

## What was found in 18.0.0.1

**The module did not do its job outside the form.** `total_surface`, `total_weight`,
`total_volume` and `price_qty` were plain stored fields, filled only by
`@api.onchange` handlers. An `@api.depends` was stacked on the same methods, which
does nothing: a depends only means something on a field's compute.

So they were filled only when a human typed into the form. A quotation template, an
import, the website shop, an API call, a duplicated order — every one of those
produced a line with `price_qty` at zero, and a line subtotal of zero. That is how
lines of normally priced products showed a subtotal of 0.00 while their order's total
was right.

**The order total ignored the magnitude.** The module forked `_compute_amount` to put
`price_qty` on the line's subtotal, but since 18.0 the order's `amount_untaxed`,
`amount_tax` and tax totals are built from `_prepare_base_line_for_taxes_computation`,
not from the lines' stored amounts. Four slabs of 12.5 kg at 3.00/kg showed **150.00**
on the line and **12.00** at the bottom of the order.

The four fields are computed stored fields now, the totals still writable, and the
fork is replaced by the hook.

`unit_price_uom_id` had no compute at all and was only ever set from a method nothing
called, so the price unit of measure on a line was always empty.

**Three overrides pointed at core methods removed in 17.0:**

- `_get_real_price_currency` returned `(0.0, False)`. Had anything still called it,
  every line would have been priced at zero.
- `update_prices` is `action_update_prices` / `_recompute_prices` now; nothing called
  the override.
- `_get_price_total_and_subtotal_model` is an `account.move.line` method from Odoo 14,
  defined here on a sale order line — so nothing ever called it — computing taxes with
  `compute_all(..., force_sign=...)`, an API the current engine does not have.

All three are gone. The six-way `price_base` branch was also a copy of
`product._get_price_qty`, which `numa_physical_product` centralises for exactly these
bridges. It delegates now.

## Upgrading from 18.0.0.1

The upgrade does not recompute a field whose column already exists, so the migration
script fills in the lines the onchange never reached (`price_qty` at zero with a
quantity), **only on orders whose products all price normally**: there the order's
total was already right and only the lines change.

An order with a product priced by a magnitude would change its total, which on a
confirmed or invoiced order is a decision for a person. Those orders are listed in the
upgrade log as a warning and left as they are. Totals typed by hand are kept.

## Tests

```bash
odoo-bin -d <database> -u numa_physical_product_sale --without-demo \
         --test-enable --test-tags=/numa_physical_product_sale --stop-after-init
```

Sixteen tests, where there were none: the line created in code being priced by its
magnitude, each of the seven price bases, unit-of-measure normalisation, the price
unit of measure, a hand-typed total being what is charged and a new quantity
overruling it, the order's weight and untaxed amount following a line, tax on the
magnitude, what `_prepare_invoice_line` carries, and that the three dead overrides are
gone.

## Author

Gustavo Marino <gamarino@numaes.com>
