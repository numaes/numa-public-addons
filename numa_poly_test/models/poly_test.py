import logging
from collections import OrderedDict

from odoo import models, fields
from odoo import api
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError


_logger = logging.getLogger(__name__)


class Test1(models.TransientModel):
    _name = 'test.test1'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('ir.poly_base', 'poly_base_id'),
    ])

    a1 = fields.Char('A1')
    a2 = fields.Char('A2')


class Test2(models.TransientModel):
    _name = 'test.test2'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a3 = fields.Char('A3')


class Test3(models.TransientModel):
    _name = 'test.test3'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a4 = fields.Char('A4')


class Test4(models.TransientModel):
    _name = 'test.test4'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test2', 'test2_id'),
        ('test.test4', 'test4_id'),
    ])

    a3 = fields.Char('A3')


class TestWizard(models.TransientModel):
    _name = 'test.test_wizard'
    _description = 'Polymorphic Test Wizard'

    def action_test1(self):
        t1_model = self.env['test.test1']
        t2_model = self.env['test.test2']
        t3_model = self.env['test.test3']
        t4_model = self.env['test.test4']


        t1_1 = t1_model.create({'a1': 'A1', 'a2': 'A2'})
        assert t1_1.a1 == 'A1'
        assert t1_1.a2 == 'A2'
        t2_1 = t2_model.create({'a3': 'A3'})
        assert t2_1.a1 == False
        assert t2_1.a2 == False
        assert t2_1.a3 == 'A3'
        t3_1 = t3_model.create({'a4': 'A4'})
        assert t3_1.a1 == False
        assert t3_1.a2 == False
        assert t3_1.a4 == 'A4'

        t2_2 = t2_model.create({'a1': 'B1', 'a2': 'B2', 'a3': 'B3'})

        return

        assert t2_2.a1 == 'B1'
        assert t2_2.a2 == 'B2'
        assert t2_2.a3 == 'B3'
        assert t2_2.test1_id == t2_2.id
        assert t2_2.concrete_model.name == 'test.test2'
        assert t2_2.test1_id.concrete_model.name == 'test.test1'

        t4_1 = t4_model.create({'a1': 'C1', 'a2': 'C2', 'a3': 'C3', 'a4': 'C4'})
        assert t4_1.a1 == 'C1'
        assert t4_1.a2 == 'C2'
        assert t4_1.a3 == 'C3'
        assert t4_1.test1_id.id == t4_1.id
        assert t4_1.test2_id.id == t4_1.id
        assert t4_1.test3_id.id == t4_1.id
        assert t4_1.concrete_model.name == 'test.test4'
        assert t4_1.test1_id.concrete_model.name == 'test.test1'
        assert t4_1.test2_id.concrete_model.name == 'test.test2'
        assert t4_1.test3_id.concrete_model.name == 'test.test3'

        t4_1.a1 = 'D1'
        t4_1.a2 = 'D2'
        t4_1.a3 = 'D3'
        t4_1.a4 = 'D4'

        assert t4_1.a1 == 'D1'
        assert t4_1.a2 == 'D2'
        assert t4_1.a3 == 'D3'
        assert t4_1.a4 == 'D4'

        t1s = t1_model.search([])
        t2s = t2_model.search([])
        t3s = t3_model.search([])
        t4s = t4_model.search([])

        assert len(t1s) == 3
        assert len(t2s) == 2
        assert len(t3s) == 1
        assert len(t4s) == 1

        poly_base_model = self.env['ir.poly_base']
        poly_base_2 = poly_base_model.browse(t4_1.id)

        assert poly_base_2.concrete_model.name == 'test.test4'
        t4_2 = poly_base_2.as_concrete_model()
        assert t4_2._name == 'test.test4'




