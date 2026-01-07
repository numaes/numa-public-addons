# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.addons.numa_poly.models.poly import PolyModel, PolyBase

class TestPolyBehaviorA(PolyModel):
    """Simple behavior model with a Char field."""
    _name = 'test.poly.behavior.a'
    _description = 'Test Poly Behavior A'
    _depend_models = {}

    field_a = fields.Char(string='Field A')

class TestPolyBehaviorB(PolyModel):
    """Behavior model with an Integer field."""
    _name = 'test.poly.behavior.b'
    _description = 'Test Poly Behavior B'
    _depend_models = {}

    field_b = fields.Integer(string='Field B')

class TestPolyProject(PolyModel):
    """Business model injecting two behaviors."""
    _name = 'test.poly.project'
    _description = 'Test Poly Project'
    _depend_models = {
        'test.poly.behavior.a': 'behavior_a_id',
        'test.poly.behavior.b': 'behavior_b_id',
    }

    name = fields.Char(string='Project Name')

class TestPolyBase(PolyModel):
    """Base model for a polymorphic hierarchy."""
    _name = 'test.poly.base'
    _description = 'Test Poly Base'
    _depend_models = {}

    base_field = fields.Char(string='Base Field')

class TestPolyChildA(PolyModel):
    """Concrete model inheriting from TestPolyBase."""
    _name = 'test.poly.child.a'
    _description = 'Test Poly Child A'
    _depend_models = {
        'test.poly.base': 'base_id',
    }

    child_a_field = fields.Char(string='Child A Field')

class TestPolyChildB(PolyModel):
    """Another concrete model inheriting from TestPolyBase."""
    _name = 'test.poly.child.b'
    _description = 'Test Poly Child B'
    _depend_models = {
        'test.poly.base': 'base_id',
    }

    child_b_field = fields.Char(string='Child B Field')
