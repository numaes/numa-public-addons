# -*- coding: utf-8 -*-
from odoo import http

# class NumaProductExtension(http.Controller):
#     @http.route('/numa_product_extension/numa_product_extension/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/numa_product_extension/numa_product_extension/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('numa_product_extension.listing', {
#             'root': '/numa_product_extension/numa_product_extension',
#             'objects': http.request.env['numa_product_extension.numa_product_extension'].search([]),
#         })

#     @http.route('/numa_product_extension/numa_product_extension/objects/<model("numa_product_extension.numa_product_extension"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('numa_product_extension.object', {
#             'object': obj
#         })