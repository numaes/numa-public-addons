# -*- coding: utf-8 -*-

{
    'name': 'NUMA Physical Product - Sale',
    'version': '20.0.1.0.0',
    'category': 'Product',
    'description': """
Technical module to expand sales by physical products
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['uom', 'numa_physical_product', 'sale_management'],
    'data': [
        'views/sale_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
    'auto_install': True,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
