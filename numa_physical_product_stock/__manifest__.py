# -*- coding: utf-8 -*-

{
    'name': 'NUMA Physical Product - Stock',
    'version': '18.0.0.2',
    'category': 'Product',
    'description': """
Technical module to expand stock by physical products
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': [
        'base',
        'numa_physical_product',
        'stock',
        # `stock.picking.sale_id` comes from `sale_stock`, and this module reads it in
        # two places: the stored `stock.move.line.sale_order_id`, and `_action_assign`,
        # which carries the unit dimensions over from the previous delivery of the same
        # sale order. It only ever ran on databases that had `sale_stock` for other
        # reasons.
        'sale_stock',
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
