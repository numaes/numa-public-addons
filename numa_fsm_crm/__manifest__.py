# -*- coding: utf-8 -*-
{
    'name': 'Numa FSM CRM',
    'version': '18.0.1.0.0',
    'summary': 'Integrates FSM capabilities into CRM Leads',
    'description': """
Numa FSM CRM
============

This module integrates Finite State Machine capabilities into CRM Leads,
allowing leads to be converted into FSM instances with automated workflows.

Key Features:
-------------
* Convert CRM leads into FSM instances
* Assign bots (FSM definitions) to leads for automated processing
* Control FSM execution from the lead form
* Visual FSM diagram showing current state
* Step-by-step debugging capabilities
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Sales/CRM',
    'depends': [
        'base',
        'crm',
        'mail',
        'numa_fsm',
        'numa_poly',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/crm_bot_views.xml',
        'views/crm_lead_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'numa_fsm_crm/static/src/css/*.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
