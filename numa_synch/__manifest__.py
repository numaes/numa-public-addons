{
    'application': True,
    'name': "NUMA Synch",
    'summary': "Keep relations between internal IDs and remote data",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "1.0",
    'category': "Synch",
    'depends': ['base'],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/synch_view.xml",
        "views/menu.xml",
    ],
}