from odoo import models, fields
from collections import OrderedDict


class Test1(models.Model):
    _name = 'test.test1'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict()

    a1 = fields.Char('A1')
    a2 = fields.Char('A2')

    def set_a1(self):
        self.a1 = 'Set by test1'


class Test2(models.Model):
    _name = 'test.test2'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a3 = fields.Char('A3')


class Test3(models.Model):
    _name = 'test.test3'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a4 = fields.Char('A4')


class Test4(models.Model):
    _name = 'test.test4'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test2', 'test2_id'),
        ('test.test3', 'test3_id'),
    ])

    a3 = fields.Char('A3 test 4')
    partner_id = fields.Many2one('res.partner', 'Test 1 related')

    def set_a1(self):
        self.a1 = 'Set by test4'

