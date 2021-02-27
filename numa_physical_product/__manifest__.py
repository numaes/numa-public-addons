# -*- coding: utf-8 -*-

{
    'name': 'NUMA Physical Product',
    'version': '1.0',
    'category': 'Product',
    'description': """
This module extends the handling of physical dimensions on products.
It adds width, heigth, length and surface.
It computes automatically surface and volume and it can compute weights automatically 
for products where the weight can be calculated on a factor multiplied by length, surface or volume

""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['base', 'product', 'stock'],
    'data': ['views/product_views.xml',
             'data/product_data.xml',
             'views/stock_views.xml'],
    'demo_xml': [],
    'test': [],
    'installable': True,
    'active': False,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
