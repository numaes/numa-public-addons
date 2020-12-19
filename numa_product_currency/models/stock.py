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

