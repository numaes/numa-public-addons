"""
Test Models for Polymorphic Inheritance

This module defines several test models that demonstrate the polymorphic
inheritance functionality. The models form a hierarchy where:

- Test1 is a base model with no dependencies
- Test2 and Test3 both depend on Test1
- Test4 depends on both Test2 and Test3, demonstrating multi-inheritance

This creates a diamond inheritance pattern:
    Test1
   /     \
Test2   Test3
   \     /
    Test4

These models are used for testing the polymorphic inheritance system.
"""

from odoo import models, fields
from collections import OrderedDict


class Test1(models.Model):
    """
    Base test model with no dependencies.

    This model serves as the root of the test inheritance hierarchy.
    It defines basic fields that will be inherited by dependent models.
    """
    _name = 'test.test1'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict()

    a1 = fields.Char('A1')
    a2 = fields.Char('A2')

    def set_a1(self):
        """Set the a1 field to a test value."""
        self.a1 = 'Set by test1'


class Test2(models.Model):
    """
    Test model that depends on Test1.

    This model inherits all fields from Test1 and adds its own field a3.
    """
    _name = 'test.test2'
    _description = 'Polymorphic Test2'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a3 = fields.Char('A3')


class Test3(models.Model):
    """
    Test model that depends on Test1.

    This model inherits all fields from Test1 and adds its own field a4.
    It demonstrates a parallel inheritance path from Test1.
    """
    _name = 'test.test3'
    _description = 'Polymorphic Test3'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a4 = fields.Char('A4')


class Test4(models.Model):
    """
    Test model that depends on both Test2 and Test3.

    This model demonstrates multiple inheritance, inheriting from both
    Test2 and Test3, which in turn both inherit from Test1. This creates
    a diamond inheritance pattern.

    It inherits all fields from Test1, Test2, and Test3, and adds its own fields.
    It also overrides the set_a1 method from Test1.
    """
    _name = 'test.test4'
    _description = 'Polymorphic Test4'

    _depend_models = OrderedDict([
        ('test.test2', 'test2_id'),
        ('test.test3', 'test3_id'),
    ])

    a3 = fields.Char('A3 test 4')
    partner_id = fields.Many2one('res.partner', 'Test 1 related')

    def set_a1(self):
        """Override the set_a1 method from Test1."""
        self.a1 = 'Set by test4'
