{
    'name': 'Numa Poly',
    'version': '18.0.1.0.0',
    'summary': 'Polymorphic model inheritance for Odoo.',
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'AGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'base',
        'numa_poly',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
}
