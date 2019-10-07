# -*- coding: utf-8 -*-
{
    'name': "numa_product_extension",

    'summary': """
        Product extensions by NUMA""",

    'description': """
        Base extensions to give more flexibility to products and pricelists
        - The possibility to create product where the price is computed per weight or
          other product attributes is its properly extended
        - Free currency to products prices and costs
        - Structured pricelist, easily extendend in dependant modules
        - Compute cost based on supplier's prices
        - Supplier's pricelists
    """,

    'author': "NUMA Extreme Systems",
    'website': "http://www.numaes.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Product',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'product'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}