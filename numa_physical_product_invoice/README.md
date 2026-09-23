# Numa Physical Product — Invoice

**Odoo 18.0** | LGPL-3 | NUMA Extreme Systems

Module version `18.0.0.1`. See [What was found](#what-was-found).

Invoices the magnitude: the kilos, metres or cubic metres a line represents, rather
than the number of pieces.

## What it adds

On an **invoice line**: the product's `unit_*` figures, the line's `total_surface`,
`total_weight` and `total_volume`, the `price_qty` the price is applied to,
`unit_price_uom_id`, and `price_base` for the view to react to.

On an **invoice**: `invoice_weight` and `invoice_volume`.

`price_qty` reaches the amounts through
`_prepare_product_base_line_for_taxes_computation`, the hook the 18.0 tax engine
calls. Every hook here is guarded by `is_invoice`, so journal entries are untouched.

## Where `price_qty` comes from

A line that arrives with its own `price_qty` **keeps it**. That is the normal case
when invoicing a sale order: for weight and volume the sale order line reads the
figure off the delivered stock moves — what was actually shipped — and passes it to
`_prepare_invoice_line`. Recomputing it here from the catalogue would bill a different
figure from the one that was picked, with both documents looking correct.

A line created without one — typed in, imported, a manual credit note — is computed
from the product and the quantity.

## Dependencies

`numa_physical_product`, `account`.

## What was found

**`create` discarded the figure the sale order had computed.** It resynced every
invoice line with a product, overwriting the `price_qty` that
`_prepare_invoice_line` had just passed in. So a customer billed by the kilo was
charged the nominal weight while the delivery note said another.

**`write` did not resync at all.** Only the form refreshed `price_qty`, through an
onchange. An edit made in code, by an import, or while building a credit note left the
previous quantity in the field the tax base is computed on — the invoice showed one
quantity and charged for another.

**The invoice totals went stale.** `_compute_weight_volume` depended on `line_ids`
alone, so a quantity change left them where they were: the list of lines had not
changed, only what was on them.

The six-way `price_base` branch was a copy of `product._get_price_qty`, which
`numa_physical_product` centralises for exactly these bridges. It delegates now.

Two overrides of `_get_fields_onchange_balance` and
`_get_fields_onchange_balance_model` are gone: both methods went with the accounting
rework several versions ago, and both overrides called a `super()` that was not
there.

## Tests

```bash
odoo-bin -d <database> -u numa_physical_product_invoice --without-demo \
         --test-enable --test-tags=/numa_physical_product_invoice --stop-after-init
```

Thirteen tests, where there were none: pricing by the magnitude for each price base,
unit-of-measure normalisation, a quantity change repricing the line, a `price_qty`
handed in being left alone, the invoice totals following their lines, a hand-typed
total, tax on the magnitude, the price unit of measure, a section line and a journal
entry being left alone, and that the two dead accounting overrides are gone.

Three of them — the ones marked as regressions — go red against the code as it stood.

## Author

Gustavo Marino <gamarino@numaes.com>
