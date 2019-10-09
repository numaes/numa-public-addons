#-*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2013
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


from odoo import fields, models, api
from odoo.tools.translate import _
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta

import logging


class numa_account_account(models.Model):
	_inherit = 'account.account'
	
	parent_id = fields.Many2one('account.account', 'Parent Account', domain=[('account_type','=','view')])
	account_type = fields.Selection([('view','View'),('imputable','Imputable')], string="Account Type")
	child_ids = fields.One2many('account.account','parent_id','Sub Levels')
	note = fields.Text('Notes')

	@api.multi
	def action(self):
		self.ensure_one()
		return True
		

class numa_account_move(models.Model):
	_inherit = 'account.move'
	
	period_id = fields.Many2one('account.period', 'Period', states={'posted':[('readonly',True)]})


class numa_account_move_line(models.Model):
	_inherit = 'account.move.line'

	period_rel = fields.Char('Period', related='move_id.period_id.name' , readonly=True)