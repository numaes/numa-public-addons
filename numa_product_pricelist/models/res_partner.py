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

from odoo import models, fields, api
from openerp.tools.translate import _

import logging
_logger = logging.getLogger(__name__)


class partner_supplier_pricelist(models.Model):
    _inherit = 'res.partner'

    profile_pricelist_customer_id = fields.Many2one(comodel_name='numa.profile_partner_pricelist', domain="[('partner_domain','=','sale')]", string='Profile Price List Customer', ondelete="restrict")
    profile_pricelist_supplier_id = fields.Many2one(comodel_name='numa.profile_partner_pricelist', domain="[('partner_domain','=','purchase')]", string='Profile Price List Supplier', ondelete="restrict")
    supplier_pricelist_id = fields.Many2one(comodel_name='product.pricelist', string='Purchase Price List')

    supplier_pricelist_count = fields.Integer('# Precios', compute='_compute_supplier_pricelist_count')
        
    @api.multi
    def action_show_supplier_pricelist(self):
        self.ensure_one()
    
        return {
            'name': _("Precios"),
            'view_mode': 'tree',
            'view_type': 'form',
            'res_model': 'product.supplierinfo',
            'res_id': False,
            'type': 'ir.actions.act_window',
            'target': 'current',
            'readonly': True,
            'context': {'search_default_name':self.id},
            'nodestroy': False,
        }

    def _compute_supplier_pricelist_count(self):
        read_group_res = self.env['product.supplierinfo'].read_group([('name', 'in', self.ids)], ['name'], ['name'])
        mapped_data = dict([(data['name'][0], data['name_count']) for data in read_group_res])
        for partner in self:
            partner.supplier_pricelist_count = mapped_data.get(partner.id, 0)
                
class numa_profile_partner_pricelist(models.Model):
    _name = 'numa.profile_partner_pricelist'

    name = fields.Char(string='Profile Price List', required=True)
    partner_domain = fields.Selection([('sale','Sale'),('purchase','Purchase')], string='Profile Domain', required=True)
    product_pricelist_ids = fields.Many2many(comodel_name='product.pricelist',relation='numa_profile_partner_pricelist_rel', column1='profile_id', column2='product_pricelist_id', string='Price List')
    note = fields.Text(string='Note')
