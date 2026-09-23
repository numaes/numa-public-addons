{
    'name': 'Numa Poly - Test',
    'version': '20.0.1.0.0',
    'summary': 'Polymorphic model inheritance for Odoo.',
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'numa_poly',
    ],
    'data': [
        'security/ir.access.csv',
        'views/poly_ui_views.xml',
    ],
    'assets': {
        'web.assets_tests': [
            'numa_poly_test/static/tests/tours/poly_ui_tours.js',
        ],
    },
    'installable': True,
}
