# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems (www.numaes.com)
#    Copyright (C) 2024
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
    'name': 'NUMA Real-Time Observability',
    'version': '18.0.0.0',
    'category': 'Extra Tools',
    'summary': 'Real-time observability mixin for Odoo models via bus notifications',
    'description': """
NUMA Real-Time Observability
============================

This module provides a mixin that can be applied to any Odoo model to enable
real-time observability through the Odoo bus system.

The mixin adds a method `real_time_notify()` that sends notifications to the
bus with the topic `observability/<model_name>`. These notifications are only
sent after a successful commit, ensuring data consistency.

Key Features:
------------
* Simple mixin-based approach - apply to any model
* Post-commit notifications - ensures data persistence
* Flexible notification data - send custom data with each notification
* Model-specific channels - automatic topic generation per model
* Error handling - robust error handling that doesn't break transactions
* Frontend and backend support - listen to notifications from both sides

For installation and API reference, see README.md. For usage examples and patterns, see USER_GUIDE.md. For implementation details, see ARCHITECTURE.md.
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['base', 'bus'],
    'data': [
        'security/security.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
    'auto_install': False,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
