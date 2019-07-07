# -*- coding: utf-8 -*-
from odoo import http

# class NumaPurchaseExtension(http.Controller):
#     @http.route('/numa_purchase_extension/numa_purchase_extension/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/numa_purchase_extension/numa_purchase_extension/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('numa_purchase_extension.listing', {
#             'root': '/numa_purchase_extension/numa_purchase_extension',
#             'objects': http.request.env['numa_purchase_extension.numa_purchase_extension'].search([]),
#         })

#     @http.route('/numa_purchase_extension/numa_purchase_extension/objects/<model("numa_purchase_extension.numa_purchase_extension"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('numa_purchase_extension.object', {
#             'object': obj
#         })