# -*- coding: utf-8 -*-

{
    'name': 'NUMA Physical Product - Stock',
    'version': '18.0.0.1',
    'category': 'Product',
    'description': """
Technical module to expand stock by physical products
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': [
        'base',
        'numa_physical_product',
        'stock'
    ],
    'data': [
        'views/stock_views.xml'
    ],
    'demo_xml': [],
    'test': [],
    'installable': True,
    'license': 'LGPL-3',
    'active': False,
    'auto_install': True,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
