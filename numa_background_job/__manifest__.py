# -*- coding: utf-8 -*-

{
    'name': 'NUMA Background Job',
    'version': '17.0.0.0',
    'category': 'Extra Tools',
    'description': """
NUMA Background Job
===================

This module adds the posibility to trigger background jobs, in order
to process long processes without blocking the UI.


""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['base', 'bus', 'web'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/background_job_views.xml',
        'views/menu_views.xml',
        'data/ir_cron.xml',
    ],
    'test': [],
    'assets': {
        'web.assets_backend': [
            'numa_background_job/static/src/css/bj_spinner.css',
            'numa_background_job/static/src/xml/bj_spinner.xml',
            'numa_background_job/static/src/js/bj_spinner_widget.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
