# -*- coding: utf-8 -*-

{
    'name': 'NUMA Physical Product - Sale',
    'version': '1.0',
    'category': 'Product',
    'description': """
Technical module to expande sales by physical products
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['base', 'numa_physical_product', 'sale'],
    'data': [
        'views/product_views.xml',
        'views/sale_views.xml',
    ],
    'demo_xml': [],
    'test': [],
    'installable': True,
    'active': False,
    'auto_install': True,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
