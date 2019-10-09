# -*- coding: utf-8 -*-
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


{
    'name': 'NUMA Shared Taxes',
    'version': '1.0',
    'category': 'Accounting',
    'description': """
Shared taxes.
=============

This module change the philosophy of taxes of OpenERP. 
It creates the notion of non-company exclusive taxes.

Legal taxes
-----------
Taxes will be related to countries and federal states. A company
will use the corresponding fed.state and country taxes, in addition
of its own particular taxes.

In order to be able to work with different companies at the same time (companies
living in the same 'tax space'), taxes references to accounts will be converted 
to properties (and thus you will provide a value for each company)

Sales & payment taxes
---------------------
On the country, federal state or company level you can define taxes
to be applicated for the sales or payment operation

Sales taxes will be applied on sale and purchases.

Payment taxes should be applied on payment and receipts operations.
THIS SHOULD BE PROVIDED IN OTHER MODULES (eg. numa_customer_voucher)

BE EXTREMELY CAREFULL ON EXISTING DATABASES. 
ALLWAYS TEST ON A BACKUP DATABASE BEFORE USING IN A PRODUCTION SYSTEM
NO FALL BACK IN CASE OF PROBLEMS


""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': [
        'base',
        'account',
        'sale',
        'purchase',
    ],
    'data': [
        'taxes_view.xml',
        'invoices_view.xml',
    ],
    'demo': [
    ],
    'test': [
    ],
    'installable': True,
    'active': False,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
