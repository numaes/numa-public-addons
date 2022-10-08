{
    'application': True,
    'name': "NUMA Finite State Machine",
    'summary': "FSM base implementation",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "1.0",
    'category': "mailing",
    'depends': [
        'base',
        'mail',
    ],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/menu_views.xml",
        "data/fsm_data.xml",
    ],
    'installable': False,
}
