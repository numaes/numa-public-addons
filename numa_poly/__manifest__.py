{
    'name': 'Numa Poly',
    'version': '20.0.1.0.0',
    'summary': 'Polymorphic model inheritance for Odoo 20.0 (patches ORM internals - '
               'version-specific; see doc/UPGRADE.md).',
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        'security/ir.access.csv',
        'data/poly_backfill_cron.xml',
    ],
    'installable': True,
    'assets': {
        'web.assets_backend': [
            'numa_poly/static/src/index.js',
            'numa_poly/static/src/views/poly_list/poly_list_renderer.js',
            'numa_poly/static/src/views/poly_list/poly_list_renderer.xml',
            'numa_poly/static/src/views/poly_list/poly_list_view.js',
            'numa_poly/static/src/views/fields/poly_field.js',
        ],
    },
    'doc': [
        'USER_GUIDE.md',
        'TECHNICAL_ANALYSIS.md',
        'doc/UPGRADE.md',
        'doc/TRANSITION.md',
    ],
}
