{
    'application': True,
    'name': "NUMA Polimorphic Models - Test suite",
    'author': "Gustavo Marino <gamarino@numaes.com>",
    'website': 'https://www.numaes.com',
    'version': "18.0.0.1",
    'category': "base",
    'depends': [
        'base',
        'numa_poly',
    ],
    'data': [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/poly_test_views.xml",
        "views/menu_views.xml",
    ],
    'installable': True,
    'license': 'LGPL-3',
}
