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

Both levels carry the magnitudes. On a variant each one is stored in a
`variant_<name>` column with a `variant_<name>_set` flag beside it, and read
through a compute that **uses the variant's value when its flag is raised and
the template's otherwise**.

The flag, not the value, is what says *this variant states its own*. Writing a
magnitude raises it — through the computed field or the raw column alike, so a
configurator writing `variant_length` needs to know nothing about flags — and
unticking it returns the variant to inheriting.

> Until 18.0.0.2 a magnitude was the variant's own when it was **not zero**.
> That made a genuine zero inexpressible: a variant of a template six metres
> long could not be a variant of no length at all. The 18.0.0.3 migration
> raises the flag exactly where the value is non-zero, so existing data keeps
> behaving as it did.

A variant derives into its own columns only while it states at least one
dimension of its own. One that states none keeps inheriting and keeps following
the template when the template's dimensions move — and a variant that stops
stating them drops the magnitudes it had derived, rather than keeping numbers
that no longer follow from anything.

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

## The translation check, which lives here for everybody

`tests/translation_check.py` holds `TranslationCoverage`, a mixin that requires
a module's `.po` to cover **every** translatable term the module exposes — not
just the messages, but field labels, help texts, selections and view strings —
read the same way `--i18n-export` reads them. It also reports entries left in
the file that no longer exist in the module.

```python
from odoo.addons.numa_physical_product.tests.translation_check import (
    TranslationCoverage)

class TestSpanish(TranslationCoverage, TransactionCase):
    TRANSLATED_MODULE = 'numa_cut_planning'
```

It is here rather than in each module because this is the lowest module the
configurator family depends on, so all of them can import it, and because
copying a check into four modules is how four copies drift.

A module whose messages are translated and whose labels are not is not half
translated: it *looks* translated, which is how it stays that way. That is what
this catches, and it caught 168 terms across four modules the day it was
written.

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
