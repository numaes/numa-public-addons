# -*- coding: utf-8 -*-

{
    'name': 'NUMA Physical Product - Purchase',
    'version': '20.0.1.0.0',
    'category': 'Product',
    'description': """
Technical module to expand purchase by physical products
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['numa_physical_product', 'purchase'],
    'data': ['views/purchase_views.xml'],
    'installable': True,
    'license': 'LGPL-3',
    'auto_install': True,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
