# -*- coding: utf-8 -*-
{
    'name': 'Numa FSM HR',
    'version': '18.0.1.0.0',
    'summary': 'Integrates FSM capabilities into HR Employees',
    'description': """
Numa FSM HR
===========

This module integrates Finite State Machine capabilities into HR Employees,
allowing employees to be converted into FSM instances with automated workflows.

Key Features:
-------------
* Convert HR employees into FSM instances
* Assign bots (FSM definitions) to employees for automated processing
* Control FSM execution from the employee form
* Visual FSM diagram showing current state
* Step-by-step debugging capabilities
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Human Resources',
    'depends': [
        'base',
        'hr',
        'mail',
        'numa_fsm',
        'numa_poly',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/hr_bot_views.xml',
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'numa_fsm_hr/static/src/css/*.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
