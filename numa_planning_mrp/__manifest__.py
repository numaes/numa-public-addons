{
    'name': 'numa_planning_mrp',
    'version': '1.0',
    'category': 'Manufacturing/Manufacturing',
    'summary': 'Bridge between MRP and Numa Planning',
    'description': """
        This module integrates Odoo Manufacturing with Numa Planning engine.
        Enables Finite Capacity Planning for Work Orders.
    """,
    'depends': ['mrp', 'numa_planning'],
    'data': [
        'views/mrp_workorder_views.xml',
        'views/mrp_production_views.xml',
    ],
    'auto_install': True,
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
