# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
{
    'name': 'NUMA Background Job - Test',
    'version': '20.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Demonstration wizard and test suite for numa_background_job',
    'description': """
NUMA Background Job - Test
==========================

A wizard that starts a background job counting to ten, so the widget can be
watched moving, and the test suite that runs the same job end to end.

Three runs are offered: one that finishes, one that reports an error halfway,
and one that raises. There is no reason to install this in production.
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['numa_background_job'],
    'data': [
        'security/ir.access.csv',
        'views/background_job_test_view.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
