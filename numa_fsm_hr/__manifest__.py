{
    'application': True,
    'name': "NUMA Finite State Machine - HR",
    'summary': "FSM CRM",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "18.0.0.1",
    'category': "mailing",
    'depends': [
        'base',
        'numa_fsm',
        'employee',
        'mail',
        'mass_mailing',
    ],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/poly_views.xml",
        "views/menu_views.xml",
    ],
    'installable': True,
    'license': 'LGPL-3',
}
