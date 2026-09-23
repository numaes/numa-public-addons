# -*- coding: utf-8 -*-
"""Give `stock.move.line.unit_*` columns before the ORM computes them from the catalogue.

Until 18.0.0.1 the three unit fields were non-stored related fields, so what an
operator weighed on a line only ever reached the stored totals. They are stored,
computed fields now, and the totals are computed from them. Left to itself, the
upgrade would create the columns, fill them with the catalogue figures, and could
recompute the historical totals from those -- replacing what each delivery actually
weighed with what the product record says.

Creating the columns here, holding the unit figure each recorded total implies,
keeps every total as it was: the ORM finds the columns already there and computes
nothing. A done or cancelled line with no recorded total gets a unit of zero, which is
what its total says; rewriting it from today's catalogue would change what that
delivery reported. Open lines with no total are left NULL and filled from the product
by the post-migration script.
"""

import logging

_logger = logging.getLogger(__name__)

MAGNITUDES = ('surface', 'weight', 'volume')


def migrate(cr, version):
    if not version:
        return
    for name in MAGNITUDES:
        # `name` comes from the tuple above, never from data.
        cr.execute("""
            ALTER TABLE stock_move_line
            ADD COLUMN IF NOT EXISTS unit_%(name)s double precision
        """ % {'name': name})
        cr.execute("""
            UPDATE stock_move_line
               SET unit_%(name)s = total_%(name)s / quantity_product_uom
             WHERE unit_%(name)s IS NULL
               AND COALESCE(total_%(name)s, 0) != 0
               AND COALESCE(quantity_product_uom, 0) != 0
        """ % {'name': name})
        _logger.info("numa_physical_product_stock: %s move lines keep their recorded %s",
                     cr.rowcount, name)
        cr.execute("""
            UPDATE stock_move_line
               SET unit_%(name)s = 0
             WHERE unit_%(name)s IS NULL
               AND state IN ('done', 'cancel')
        """ % {'name': name})
