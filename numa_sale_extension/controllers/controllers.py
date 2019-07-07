# -*- coding: utf-8 -*-
from odoo import http

# class NumaSaleExtension(http.Controller):
#     @http.route('/numa_sale_extension/numa_sale_extension/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/numa_sale_extension/numa_sale_extension/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('numa_sale_extension.listing', {
#             'root': '/numa_sale_extension/numa_sale_extension',
#             'objects': http.request.env['numa_sale_extension.numa_sale_extension'].search([]),
#         })

#     @http.route('/numa_sale_extension/numa_sale_extension/objects/<model("numa_sale_extension.numa_sale_extension"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('numa_sale_extension.object', {
#             'object': obj
#         })