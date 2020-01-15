# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems.
#  
#    Copyright (C) 2013 NUMA Extreme Systems (<http:www.numaes.com>).
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
    'name': 'NUMA IMAP',
    'author' : 'Numa Extreme Systems',
    'category' : 'Specific Numa Applications',
    'description': """
NUMA IMAP extension
===================
    * Leave read mails from IMAP servers as unread on server
""",
	'summary': "IMAP extension",
    'version': '1.0',
    'depends': ['base','fetchmail'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/fetchmail_views.xml',
    ],
    'auto_install': False,
    'application': False,
}
