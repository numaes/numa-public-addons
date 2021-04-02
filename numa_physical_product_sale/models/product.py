from odoo import fields, models, api

import logging
_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    price_base = fields.Selection(
        [('normal', 'Normal, per product UoM'),
         ('length', 'Based on length [m]'),
         ('width', 'Based on width [m]'),
         ('height', 'Based on height [m]'),
         ('weight', 'Based on weight [kg]'),
         ('surface', 'Based on surface [m2]'),
         ('volume', 'Based on volume [m3]')],
        'Base of price',
        default='normal',
        required=True,
    )

