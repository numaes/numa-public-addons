{
    'name': 'Numa Poly',
    'version': '18.0.1.0.0',
    'summary': 'Polymorphic model inheritance for Odoo 18.0 (patches ORM internals — '
               'version-specific; see doc/UPGRADE.md).',
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'AGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        'data/poly_backfill_cron.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
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
    ],
}
