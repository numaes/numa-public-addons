# -*- coding: utf-8 -*-
{
    'name' : 'Numa Roles',
    'version' : '1.0',
    'author' : 'Numa Extreme Systems',
    'category' : 'Specific Numa Applications',
    'website': 'https://www.numaes.com',
    'depends' : ['web','base'],
    'demo' : [],
    'data' : ['security/ir.model.access.csv',
              'security/security.xml',
              'views/roles_view.xml',
              'data/initial_roles.xml',
    ],
    'description': """Role Management""",
    'summary': 'Roles and Permitions',
    'css': [],
    'auto_install': False,
    'installable': True,
    'application': True,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
