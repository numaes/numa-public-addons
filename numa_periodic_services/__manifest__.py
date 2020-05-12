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
    'name': 'NUMA Periodic Services',
    'author' : 'Numa Extreme Systems',
    'category' : 'Specific Numa Applications',
    'description': """
Periodic services administration.
=================================

 This module executes periodic service in an easy to maintain strategy.

A service could in operational state and then it runs periodically according
the programmed interval period.

A service could be configured, tested or put into maintenance state. In this 
states no programmed execution occurs, and thus could be easyly controlled by
the operator.

Every time an execution occurs, it is logged on the standard log.
If an exception occurs, the transaction will be rolled back at the next available
step.

You can set up the service so it will move to maintenance state automatically
if an exception occurs. If not, the run will be retried for ever til a no exception
execution.

The basic service dispatch occurs at a period of 10 minutes. All services will be
checked to run the ones wich its next run is already happened.

""",
	'summary': "Periodic Services administration",
    'version': '1.0',
    'depends': ['base',
                'numa_exceptions'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/periodic_services_views.xml',
        'data/periodic_services_data.xml',],
    'auto_install': False,
    'application': True,
}
