# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
{
    'name': 'NUMA Real-Time Observability - Test',
    'version': '20.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Probe model and test suite for numa_real_time_observability',
    'description': """
NUMA Real-Time Observability - Test
===================================

A mixin can only be tested on a model that inherits it, and a model can only
be registered by a module. This module exists to provide that model:
``numa.observability.probe`` does nothing except carry the mixin.

Install it to run the suite; there is no reason to install it in production.
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['numa_real_time_observability'],
    'data': [
        'security/ir.access.csv',
    ],
    'installable': True,
    'license': 'LGPL-3',
    'auto_install': False,
}
