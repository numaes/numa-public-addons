# -*- coding: utf-8 -*-

{
    'name': 'NUMA Physical Product - Invoice',
    'version': '1.0',
    'category': 'Product',
    'description': """
Technical module to expand invoices by physical products
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': [
        'base',
        'numa_physical_product',
        'account'
    ],
    'data': [
        'views/invoice_views.xml'
    ],
    'demo_xml': [],
    'test': [],
    'installable': True,
    'active': False,
    'auto_install': True,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
