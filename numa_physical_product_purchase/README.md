# Numa Physical Product — Purchase

**Odoo 18.0** | LGPL-3 | NUMA Extreme Systems

Module version `18.0.0.2`. Up to `18.0.0.1` **it did not price anything by its
magnitude**: see [What was found](#what-was-found-in-18001).

Buys by the kilo, the metre, the square metre and the cubic metre — the purchase side
of [`numa_physical_product_sale`](../numa_physical_product_sale/README.md).

## What it adds

On a **purchase order line**: the product's `unit_*` figures, the line's writable
`total_surface`, `total_weight` and `total_volume`, the `price_qty` the price is
applied to, and `unit_price_uom_id`, which names what the unit price is per.

On a **purchase order**: `po_weight` and `po_volume`.

`price_qty` reaches the amounts through `_prepare_base_line_for_taxes_computation`,
the hook the 18.0 tax engine calls for the line and for the order totals.

## Dependencies

`numa_physical_product`, `purchase`.

## What was found in 18.0.0.1

**Nothing read `price_qty`.** The tax base was handed over through
`_convert_to_tax_base_line_dict`, a hook core stopped calling when the tax engine was
rebuilt, so every purchase was costed by the unit whatever its price base: four slabs
of 12.5 kg at 3.00/kg came to **12.00** instead of **150.00**.

**The four fields were filled only in the form.** They were plain stored fields filled
by `@api.onchange` handlers, so a line created by an import, a replenishment rule or
an API call kept them at zero.

**The quantity was normalised twice.** `product_uom_qty` is already the quantity in the
product's own unit of measure — core computes it as
`product_uom._compute_quantity(product_qty, product.uom_id)` — and the module converted
it again. A line bought in dozens reported twelve times the weight it carried.

**`_onchange_quantity` overrode a core method with its `super()` commented out.** Core
has no method of that name in 18.0, so the override shadowed nothing — but it is
exactly the shape that silently disables a core handler the moment core adds one back.

The totals and `price_qty` are computed stored fields now; the totals stay writable,
because the delivery is weighed on arrival and that figure is what the vendor invoices
against. `_compute_amount` depends on `price_qty`, so a total typed over by hand moves
a subtotal that was already computed. The six-way `price_base` branch delegates to
`product._get_price_qty`.

## Upgrading from 18.0.0.1

The migration script fills in `price_qty` and the totals on the lines the onchange
never reached, only on orders whose products all price normally, where the order
total does not change. Orders with a product priced by a magnitude are listed in the
upgrade log and left as they are.

## Tests

```bash
odoo-bin -d <database> -u numa_physical_product_purchase --without-demo \
         --test-enable --test-tags=/numa_physical_product_purchase --stop-after-init
```

Thirteen tests, where there were none: the line created in code being priced by its
magnitude, a quantity change moving the price, the single normalisation, each of the
seven price bases, the price unit of measure, a hand-typed total being what is paid
and a new quantity overruling it, the order's weight and untaxed amount following a
line, tax on the magnitude, and that the shadowing override is gone.

## Author

Gustavo Marino <gamarino@numaes.com>
