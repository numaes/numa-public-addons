{
    'name': 'numa_planning_purchase',
    'version': '1.0',
    'category': 'Inventory/Purchase',
    'summary': 'Bridge between Purchase and Numa Planning with AI hooks',
    'description': """
        This module integrates Odoo Purchase with Numa Planning engine.
        It treats Purchase Order Lines as planning nodes and Suppliers as resources.
        Includes AI hooks for lead time and prioritization.
    """,
    'depends': ['purchase', 'numa_planning'],
    'data': [
        'views/purchase_order_views.xml',
    ],
    'auto_install': True,
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
