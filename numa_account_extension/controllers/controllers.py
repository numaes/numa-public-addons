# -*- coding: utf-8 -*-
from odoo import http

# class NumaAccountExtension(http.Controller):
#     @http.route('/numa_account_extension/numa_account_extension/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/numa_account_extension/numa_account_extension/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('numa_account_extension.listing', {
#             'root': '/numa_account_extension/numa_account_extension',
#             'objects': http.request.env['numa_account_extension.numa_account_extension'].search([]),
#         })

#     @http.route('/numa_account_extension/numa_account_extension/objects/<model("numa_account_extension.numa_account_extension"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('numa_account_extension.object', {
#             'object': obj
#         })