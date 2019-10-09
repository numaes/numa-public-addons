##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
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
{
	'name' : 'Numa Product Price List',
	'version' : '1.0',
	'author' : 'Numa Extreme Systems',
	'category' : 'Specific Numa Applications',
	'website': 'https://www.numaes.com',
	'depends' : ['numa_product_advanced_configurator','numa_product_serial_number','numa_product_lot_extend','decimal_precision','numa_l10n_ar_base'],
	'demo' : [],
	'data' : ['views/numa_product_pricelist_view.xml',
			  'views/numa_product_global_discount_view.xml',
			  'views/invoice_view.xml',
			  'views/sale_order_view.xml',
			  'views/purchase_order_view.xml',
			  'security/ir.model.access.csv',
			  'security/security.xml',
			  'views/product_view.xml',
			  'views/res_partner_view.xml',],
	'css': [],
	'description': """Manager Product Price List""",
	'summary': 'Manager Product Price List',
	'auto_install': False,
	'installable': True,
	'application': True,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
