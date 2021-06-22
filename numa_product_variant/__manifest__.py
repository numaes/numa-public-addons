{
    'name': 'NUMA Product Variant',
    'version': '1.0',
    'category': 'Product',
    'description': """
This module extends the handling of variants on products.
It adds:
- Base code on templates
- Initial attributes to be added on product creation on categories
- Attribute codes used to construct variant default_code, adding to base_code on template

""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['base', 'product', 'numa_physical_product'],
    'data': [
        'views/product_views.xml',
    ],
    'demo_xml': [],
    'test': [],
    'installable': True,
    'active': False,
}
