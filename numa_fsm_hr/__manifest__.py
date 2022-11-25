{
    'application': True,
    'name': "NUMA FSM Human Resource",
    'summary': "HR Workflow",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "1.0",
    'category': "mailing",
    'depends': [
        'base',
        'numa_fsm_crm',
        'hr',
    ],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/fsm_views.xml",
        "views/menu_views.xml",
    ],
}
