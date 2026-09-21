# Numa Physical Product — Stock

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Before the migration
**no stock could move at all** with it installed, and the one thing it exists to record
was being thrown away: see [What was found](#what-was-found-before-migrating).

Records what a delivery actually weighed, on the delivery. A batch of slabs is not the
catalogue slab, and when the customer is billed by the kilo the difference is the
invoice.

## What it adds

On a **stock move line**:

| Field | Meaning |
| --- | --- |
| `unit_surface`, `unit_weight`, `unit_volume` | this line's figures — opened from the product and corrected by the operator |
| `unit_width`, `unit_length`, `unit_height` | the product's, for reference |
| `total_surface`, `total_weight`, `total_volume` | unit × quantity, and writable the other way round: the operator weighs the pallet, not the piece, so entering a total sets the unit |
| `partner_id`, `sale_order_id` | stored, so deliveries can be grouped and reported on |

On a **stock move**: the same three totals, summed from its lines — or, before
anything is reserved, the demand times the product's figures.

On a **picking**: `picking_weight` and `picking_volume`.

## Where the figures come from

1. A new move line opens at the product's figures.
2. `_prepare_move_line_vals` prefers what the same product weighed the **last time it
   arrived at this location**, which is a better opening figure than the catalogue's.
3. `_action_assign` prefers what the **previous delivery of the same sale order**
   weighed, so a split delivery stays consistent with itself.
4. The operator corrects either figure, in whichever direction is convenient.

What lands there is what `numa_physical_product_sale` bills for a product priced by
weight or volume.

## Dependencies

`numa_physical_product`, `stock`, `sale_stock` — the last one because this module reads
`stock.picking.sale_id`, which comes from it.

## What was found before migrating

**The module made stock unusable.** `stock.move.line.product_uom_id` is `uom_id` in
Odoo 20. The old name was read from a method `create` called on every move line, so it
raised `AttributeError` before any stock could move — confirming a sale order died
inside `_action_assign`, with a message naming a field nobody had heard of.

**And the per-line dimensions were being discarded.** `unit_surface`, `unit_weight` and
`unit_volume` were non-stored related fields (`related='product_id.weight'`,
`readonly=True`) — and `_prepare_move_line_vals`, `_action_assign` and the total
handlers all wrote to them. A write to a non-stored related field lands in the cache
and nowhere else: it read back correctly inside the transaction and was the product's
figure again the moment the cache was dropped. Everything above — the last arrival's
weight, the previous delivery's weight, the operator's correction — evaporated without
a word. They are stored, seeded from the product and writable now, which is what the
surrounding code always assumed.

**The quantity was normalised twice.** `quantity_product_uom` is already the quantity
in the product's own unit — core computes it as
`uom_id._compute_quantity(quantity, product.uom_id)` — and the module converted it
again. A line entered in dozens reported twelve times the weight it carried: 2 dozen
slabs of 10 kg came to 2880 kg instead of 240.

**The picking's compute named a field Odoo 20 removed.** `move_line_ids_without_package`
was a helper for the detailed-operations widget; a `@depends` naming a field that does
not exist raises while the trigger tree is built, so the module could not install.

**And the totals were kept up to date by hand.** They were plain fields refreshed by
`create` and `write` overrides that fired on two specific keys, with an inert
`@api.depends` stacked on the same method. Every other path left them stale. The move's
fallback for "no lines yet" read `quantity`, which in 20.0 is itself computed from the
move lines — so in the only case the fallback exists for, it was always zero. It reads
`product_qty`, the demand, now.

## Tests

```bash
odoo-bin -d <database> -u numa_physical_product_stock --without-demo \
         --test-enable --test-tags=/numa_physical_product_stock --stop-after-init
```

Sixteen tests, where there were none: that a move line can be created at all, that a
dimension entered on the line survives a flush and that the catalogue is not edited by
it, the totals and their inverse, a total on a zero quantity, the single
normalisation, the move and the picking adding up and following a correction, the
move's fallback before anything is reserved, and both sources a new line is seeded
from.

## Author

Gustavo Marino <gamarino@numaes.com>
