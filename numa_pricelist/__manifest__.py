{
    'name': 'NUMA Pricelist',
    'version': '1.0',
    'category': 'Product',
    'description': """
This module changes and extends the base Odoo pricelist functionality.
It adds:
- Better management of submodules to add criteria for pricelist rule triggering and computing.
  It is easy to extenden this module and add new functionality without breaking the monolithic computing function
- A new rule for rule triggering taking into account product attributes
- Price can be base on prefered supplier's price
- Expansion of categories, products and variants as triggers to a list of values (for example
  several categories could lead to the same result without duplicating the rule)

""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': [
        'base',
        'product',
        'numa_product_currency'
    ],
    'data': [
        'views/pricelist_views.xml',
    ],
    'demo_xml': [],
    'test': [],
    'installable': True,
    'active': False,
}
