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
#from datetime import datetime, timedelta, date

import logging
_logger = logging.getLogger(__name__)

class holiday(models.Model):
    _name = 'account.holiday'
    _rec_name = 'date'

    country = fields.Many2one('res.country', 'Country', required=True)
    date =  fields.Date('Date', required=True)
    description =  fields.Char('Description')
    holiday_type = fields.Selection([('optional','Optional'),('mandatory','Mandatory')], string='Holiday type', required=True, default='mandatory')
    notes = fields.Text('Notes')
    
    @api.multi
    def name_get(self):
        res=[]
        for holiday in self:
            res.append((holiday.id,'[%s - %s]' % (holiday.country.code, holiday.date)))
            
        return res
