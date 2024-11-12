{
    'application': True,
    'name': "NUMA Finite State Machine",
    'summary': "FSM base implementation",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "18.0.0.1",
    'category': "mailing",
    'depends': [
        'base',
        'mail',
        'mass_mailing',
    ],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/fsm_views.xml",
        "views/menu_views.xml",
        "views/fsm_templates.xml",
        "data/fsm_data.xml",
    ],
    'installable': True,
    'license': 'LGPL-3',
}
