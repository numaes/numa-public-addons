# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2015
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

from odoo import models, fields, api, tools, _
from collections import defaultdict
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = "stock.move"

    def _prepare_account_move_line(self, qty, cost, credit_account_id, debit_account_id, description):
        res = super(StockMove, self)._prepare_account_move_line(
            qty, cost, credit_account_id, debit_account_id, description
        )
        new_res = []
        product_id = self.env['product.product'].browse(res[0][2]['product_id'])
        for tuple in res:
            if not self.company_id.currency_id.id == product_id.cost_currency.id:
                tuple[2]['amount_currency'] = tuple[2]['debit'] - tuple[2]['credit']
                tuple[2]['currency_id'] = product_id.cost_currency.id
                tuple[2]['debit'] = product_id.cost_currency.compute(
                    tuple[2]['debit'], self.company_id.currency_id, round=False
                )
                tuple[2]['credit'] = product_id.cost_currency.compute(
                    tuple[2]['credit'], self.company_id.currency_id, round=False
                )
            new_res.append(tuple)

        return new_res

    def get_price_unit(self):
        """ Returns the unit price to store on the quant """
        if self.purchase_line_id:
            order = self.purchase_line_id.order_id
            #if the currency of the PO is different than the company one, the price_unit on the move must be reevaluated
            #(was created at the rate of the PO confirmation, but must be valuated at the rate of stock move execution)
            #we don't pass the move.date in the compute() for the currency rate on purpose because
            # 1) get_price_unit() is supposed to be called only through move.action_done(),
            # 2) the move hasn't yet the correct date (currently it is the expected date, after
            #    completion of action_done() it will be now() )
            price_unit = self.company_id.currency_id.compute(
                self.purchase_line_id._get_stock_move_price_unit(),
                self.product_id.cost_currency,
                round=False,
            )
            self.write({'price_unit': price_unit})
            return price_unit

        return self.company_id.currency_id.compute(
            super(StockMove, self).get_price_unit(),
            self.product_id.cost_currency,
            round=False,
        )

