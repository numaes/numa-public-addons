{
    'application': True,
    'name': "NUMA Synch",
    'summary': "Keep relations between internal IDs and remote data",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "18.0.0.1",
    'category': "Synch",
    'depends': ['base', 'mail'],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/synch_view.xml",
        "views/menu.xml",
    ],
    'installable': True,
    'license': 'LGPL-3',
}
