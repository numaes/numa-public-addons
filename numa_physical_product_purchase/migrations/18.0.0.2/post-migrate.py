# -*- coding: utf-8 -*-
"""Fill in the purchase order lines the onchange never reached.

Until 18.0.0.1 `total_*` and `price_qty` were plain stored fields filled only by
onchange handlers, so a line created outside the form -- an import, an API call,
a replenishment rule -- kept them at zero. They are computed fields now, but the
upgrade does not recompute a field whose column already exists, so those lines
would stay at zero.

On an order whose products all price normally, recomputing only corrects the lines:
the order's own amounts were already built from the ordered quantity, and still are.
On an order with a product priced by a physical magnitude it would also change the
order's total, which on a confirmed or invoiced order is a decision for a person, not
for an upgrade. Those are listed in the log and left alone.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

RECOMPUTED = ('total_surface', 'total_weight', 'total_volume', 'price_qty',
              'price_subtotal', 'price_tax', 'price_total')


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT l.id, o.name, bool_and(pt_all.price_base = 'normal')
          FROM purchase_order_line l
          JOIN purchase_order o ON o.id = l.order_id
          JOIN purchase_order_line l_all ON l_all.order_id = o.id AND l_all.display_type IS NULL
          JOIN product_product p_all ON p_all.id = l_all.product_id
          JOIN product_template pt_all ON pt_all.id = p_all.product_tmpl_id
         WHERE l.display_type IS NULL
           AND l.product_id IS NOT NULL
           AND COALESCE(l.price_qty, 0) = 0
           AND COALESCE(l.product_qty, 0) != 0
         GROUP BY l.id, o.name
    """)
    rows = cr.fetchall()
    safe = [line_id for line_id, _name, all_normal in rows if all_normal]
    held = sorted({name for _line_id, name, all_normal in rows if not all_normal})

    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['purchase.order.line']
    lines = Line.browse(safe)
    if lines:
        for name in RECOMPUTED:
            env.add_to_compute(Line._fields[name], lines)
        env.flush_all()
    _logger.info("numa_physical_product_purchase: %s lines filled in", len(lines))

    if held:
        _logger.warning(
            "numa_physical_product_purchase: %s orders have lines priced by a physical magnitude whose "
            "price_qty was never filled in. Recomputing them would change the order "
            "total, so they were left as they are; review them by hand: %s",
            len(held), ', '.join(held))
