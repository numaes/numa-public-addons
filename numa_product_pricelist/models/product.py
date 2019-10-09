# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2017
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import models, fields, api, tools
from itertools import chain

from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.multi
    def price_compute(self, price_type, uom=False, currency=False, company=False):
        res = {}
        for product in self:
            if price_type not in ['supplier_list', 'supplier_actual']:
                res[product.id] = super(ProductProduct, product).price_compute(
                    price_type,
                    uom=uom,
                    currency=currency,
                    company=company
                )[product.id]
            else:
                res[product.id] = 0.0
                if product.seller_ids:
                    currentSeller = product.seller_ids[0]
                    price = currentSeller.price
                    if currency and currentSeller.currency_id != currency:
                        price = currentSeller.currency_id.compute(price, currency)
                    if price_type == 'supplier_actual' and \
                       currentSeller.name.supplier_pricelist_id:
                        price = currentSeller.name.supplier_pricelist_id.get_product_price(
                            product, 1.0
                        )
                        if currency and currentSeller.name.supplier_pricelist_id.currency_id != currency:
                            price = currentSeller.name.supplier_pricelist_id.currency_id.compute(price, currency)
                    res[product.id] = price

        return res