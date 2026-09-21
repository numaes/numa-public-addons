# Numa Physical Product — Purchase

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Before the migration
**it did nothing at all**: see [What was found](#what-was-found-before-migrating).

Buys by the kilo, the metre, the square metre and the cubic metre — the purchase side
of [`numa_physical_product_sale`](../numa_physical_product_sale/README.md).

## What it adds

On a **purchase order line**: the product's `unit_*` figures, the line's writable
`total_surface`, `total_weight` and `total_volume`, the `price_qty` the price is
applied to, and `unit_price_uom_id`, which names what the unit price is per.

On a **purchase order**: `po_weight` and `po_volume`.

`price_qty` reaches the amounts through
`_prepare_base_line_for_taxes_computation`, the hook Odoo 20's tax engine calls.

## Dependencies

`numa_physical_product`, `purchase`.

## What was found before migrating

**Nothing in this module worked, in the form or out of it.** The four fields were
plain stored fields filled by `@api.onchange` handlers keyed on `product_uom_qty` —
and on `purchase.order.line` in Odoo 20 `product_uom_qty` is a *computed* field. The
quantity a buyer types is `product_qty`. So the handlers never fired on a quantity
edit, `price_qty` stayed at zero everywhere, and since `price_qty` is what goes on the
tax base, four slabs of 12.5 kg at 3.00/kg were costed at **12.00** instead of
**150.00**.

Eleven of this module's twelve tests fail against the code as it stood.

**The quantity was normalised twice.** `product_uom_qty` is already the quantity in the
product's own unit of measure — core computes it as
`uom_id._compute_quantity(product_qty, product.uom_id)` — and the module converted it
again. A line bought in dozens reported twelve times the weight it carried.

**`_onchange_quantity` overrode a core method with its `super()` commented out.** Core
has no method of that name in 20.0, so the override shadowed nothing — but it is
exactly the shape that silently disables a core handler the moment core adds one back.

The totals and `price_qty` are computed stored fields now; the totals stay writable,
because the delivery is weighed on arrival and that figure is what the vendor invoices
against. The six-way `price_base` branch delegates to `product._get_price_qty`.

## Tests

```bash
odoo-bin -d <database> -u numa_physical_product_purchase --without-demo \
         --test-enable --test-tags=/numa_physical_product_purchase --stop-after-init
```

Twelve tests, where there were none: the line created in code being priced by its
magnitude, a quantity change moving the price, the single normalisation, each of the
seven price bases, the price unit of measure, a hand-typed total being what is paid
and a new quantity overruling it, the order's totals following a line, tax on the
magnitude, and that the shadowing override is gone.

## Author

Gustavo Marino <gamarino@numaes.com>
