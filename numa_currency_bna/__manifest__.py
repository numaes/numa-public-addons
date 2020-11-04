{
    'application': True,
    'name': "NUMA BNA synch",
    'description': """Sincronización de tasas de cambio del sitio de Banco de la Nación Argentina""",
    'summary': "Sincronización de tasas de cambio del sitio de Banco de la Nación Argentina",
    'author': 'Numa Extreme Systems',
    'website': 'https://www.numaes.com',
    'version': "1.0",
    'category': "Accounting",
    'depends': ['account'],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/bna_synch_views.xml",
        "data/bna_synch_data.xml",
    ],
}
