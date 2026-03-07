# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

import logging

_logger = logging.getLogger(__name__)


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    base = fields.Selection(selection_add=[('volume', 'Volume, price per m3'),
                                           ('surface', 'Surface, price per m2'),
                                           ('weight', 'Weight, price per kg'),
                                           ('length', 'Length, price per m'),
                                           ('width', 'Width, price per m'),
                                           ('height', 'Height, price per m')],
                            ondelete={'volume': 'set default',
                                      'surface': 'set default',
                                      'weight': 'set default',
                                      'length': 'set default',
                                      'width': 'set default',
                                      'height': 'set default'})
