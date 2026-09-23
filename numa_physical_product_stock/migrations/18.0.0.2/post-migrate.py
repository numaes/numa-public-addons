# -*- coding: utf-8 -*-
"""Seed from the product the unit figures no recorded total could provide.

The pre-migration script derived `unit_*` from each line's recorded total, and gave
closed lines without one a zero. An open line with no total has nothing to derive it
from; it takes the catalogue figure, which is what a line created today gets, and its
totals follow.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MAGNITUDES = ('surface', 'weight', 'volume')


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    MoveLine = env['stock.move.line']
    for name in MAGNITUDES:
        # `name` comes from the tuple above, never from data.
        cr.execute("SELECT id FROM stock_move_line WHERE unit_%s IS NULL" % name)
        lines = MoveLine.browse([row[0] for row in cr.fetchall()])
        if lines:
            env.add_to_compute(MoveLine._fields['unit_%s' % name], lines)
        _logger.info("numa_physical_product_stock: %s move lines take their %s from the product",
                     len(lines), name)
    env.flush_all()
