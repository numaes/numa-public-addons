# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2014
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
    'name' : 'Numa Account Extended',
    'version' : '1.0',
    'author' : 'Numa Extreme Systems',
    'category' : 'Specific Numa Applications',
    'website': 'https://www.numaes.com',
    'depends' : ['web','base','account','product','sale','purchase','stock','hr','web_notify','numa_background_job'],
    'demo' : [],
    'js': 'static/src/js/check_image_on_hover.js',
    'data' : ['views/account_view.xml',
			  'views/account_fiscalyears_view.xml',
			  'views/holiday_view.xml',
              'views/cheques_view.xml',
			  'views/partner_view.xml',
              'views/product_view.xml',
              'views/invoice_view.xml',
              'views/retenciones_percepciones_view.xml',
              'views/check_image_on_hover.xml',
              'views/sale_order_view.xml',
              'views/purchase_order_view.xml',
              'security/ir.model.access.csv',
              'security/numa_account_extended_security.xml'
			  ],
    'description': """Account Managenment""",
    'summary': 'Account Management Extended',
    'css': ['static/src/css/numa_account_extended.css'],
    'auto_install': False,
    'installable': True,
    'application': True,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
