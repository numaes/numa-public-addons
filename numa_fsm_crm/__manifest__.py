{
    'application': True,
    'name': "NUMA Finite State Machine - CRM",
    'summary': "FSM CRM",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "1.0",
    'category': "mailing",
    'depends': [
        'base',
        'numa_fsm',
        'crm',
        'mail',
        'mass_mailing',
        'email_template_qweb',
    ],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/fsm_views.xml",
        "views/menu_views.xml",
        "views/fsm_templates.xml",
    ],
}