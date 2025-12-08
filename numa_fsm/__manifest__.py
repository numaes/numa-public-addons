{
    'application': True,
    'name': "NUMA Finite State Machine",
    'summary': "FSM base implementation",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "18.0.0.3",
    'category': "mailing",
    'depends': [
        'base',
        'mail',
        'mass_mailing',
        'website',
        'numa_poly'
    ],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/fsm_views.xml",
        "views/fsm_log_views.xml",
        "views/menu_views.xml",
        "views/fsm_templates.xml",
        "data/fsm_data.xml",
        "data/ir_cron.xml",
    ],
    'assets': {
        'web.assets_backend': [
            'numa_fsm/static/src/components/fsm_graph_view/fsm_graph_view.js',
            'numa_fsm/static/src/components/fsm_graph_view/fsm_graph_view.xml',
            'numa_fsm/static/src/components/fsm_graph_view/fsm_graph_view.scss',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
