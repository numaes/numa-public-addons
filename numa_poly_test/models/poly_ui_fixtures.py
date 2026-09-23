# -*- coding: utf-8 -*-
"""Fixtures for the polymorphic list view and x2many widget.

`test.poly.site` holds a one2many of `test.test1`, a polymorphic base whose subtypes
are `test.test2`, `test.test3` and `test.test4`. Its form uses
`widget="numa_polimorphic_widget"`, and the `test.test1` list uses
`js_class="poly_list"`.
"""
from odoo import fields, models


class TestPolySite(models.Model):
    _name = 'test.poly.site'
    _description = 'Polymorphic UI Site'

    name = fields.Char(required=True)
    item_ids = fields.One2many('test.test1', 'site_id', string='Items')


class Test1Site(models.Model):
    _inherit = 'test.test1'

    site_id = fields.Many2one('test.poly.site', string='Site', ondelete='cascade')
