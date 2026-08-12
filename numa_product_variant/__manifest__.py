{
    'name': 'NUMA Product Variant',
    'version': '18.0.0.3',
    'category': 'Product',
    'description': """
This module extends the handling of variants on products.
It adds:
- Base code on templates
- Initial attributes to be added on product creation on categories
- Attribute codes used to construct variant default_code, adding to base_code on template
- Product configurator on Purchase Orders, reusing the Sales configurator to pick or create a variant from a product template on a purchase order line

""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['base', 'product', 'numa_physical_product', 'sale', 'purchase'],
    'data': [
        'data/ir_cron.xml',
        'views/product_views.xml',
        'views/purchase_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'numa_product_variant/static/src/js/purchase_product_configurator_dialog.js',
            'numa_product_variant/static/src/js/purchase_product_field.js',
            'numa_product_variant/static/src/js/open_value_configurator.js',
            'numa_product_variant/static/src/xml/open_value_configurator.xml',
        ],
    },
    'demo_xml': [],
    'test': [],
    'installable': True,
    'license': 'LGPL-3',
    'active': False,
}
