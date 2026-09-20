# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
{
    'name': 'NUMA Real-Time Observability',
    'version': '20.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Real-time observability mixin for Odoo models via bus notifications',
    'description': """
NUMA Real-Time Observability
============================

A mixin that lets any Odoo model publish what happens to it, live, over the
Odoo bus.

Inheriting the mixin adds ``real_time_notify()``. It sends one message per
record to the **Real-Time Observer** group, under the notification type
``observability/<model_name>``, which is what a client subscribes to.

Key Features:
-------------
* Simple mixin-based approach - apply to any model
* The group is the channel, so only its members can listen
* One notification type per model, which is what the bus client filters on
* Notifications reach their subscribers only once the transaction commits
* Optional condition, to publish only what is worth watching
* Errors are logged and never break the transaction that published

Migrated to Odoo 20.0. See README.md for the list of changes.

For installation and API reference, see README.md. For usage examples and patterns, see USER_GUIDE.md. For implementation details, see ARCHITECTURE.md.
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['bus'],
    'data': [
        'security/numa_real_time_observability_security.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
    'auto_install': False,
}
