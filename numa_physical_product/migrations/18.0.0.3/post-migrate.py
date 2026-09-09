# -*- coding: utf-8 -*-
"""Carry the old "zero means inherit" convention into explicit flags.

Until 18.0.0.2 a variant magnitude was the variant's own when it was not zero.
That made a genuine zero inexpressible, so each magnitude now has a flag beside
it saying whether the variant states its own value. Raising the flag exactly
where the value is non-zero reproduces the previous behaviour for every
existing row; nothing changes until somebody edits a variant.
"""

import logging

_logger = logging.getLogger(__name__)

MAGNITUDES = ('weight_factor', 'weight', 'volume', 'surface',
              'width', 'height', 'length')


def migrate(cr, version):
    if not version:
        return
    for name in MAGNITUDES:
        # `name` comes from the tuple above, never from data.
        cr.execute("""
            UPDATE product_product
               SET variant_%(name)s_set = TRUE
             WHERE variant_%(name)s IS NOT NULL
               AND variant_%(name)s != 0
               AND variant_%(name)s_set IS NOT TRUE
        """ % {'name': name})
        _logger.info("numa_physical_product: %s variants keep their own %s",
                     cr.rowcount, name)
