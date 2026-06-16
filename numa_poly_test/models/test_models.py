"""
Test Models for Polymorphic Inheritance

This module defines several test models that demonstrate the polymorphic
inheritance functionality. The models form a hierarchy where:

- Test1 is a base model with no dependencies
- Test2 and Test3 both depend on Test1
- Test4 depends on both Test2 and Test3, demonstrating multi-inheritance

This creates a diamond inheritance pattern:
    Test1
   /     \\
Test2   Test3
   \\     /
    Test4

These models are used for testing the polymorphic inheritance system.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError
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
    # active: hace al concreto archivable (patrón de producción; ej. res.partner como base poly).
    active = fields.Boolean(default=True)
    # Campos para cubrir m2m y computed-stored sobre un modelo poly (patrones de producción).
    tag_ids = fields.Many2many('res.partner.category', string='Tags')
    # one2many a un modelo regular cuyo m2o apunta a este modelo poly.
    line_ids = fields.One2many('test.test4.line', 'parent_id', string='Lines')
    # Computed STORED que depende de un campo HEREDADO (a1, vive en test.test1): ejercita el
    # disparo del recompute cuando cambia un campo de una base compartida.
    a1_upper = fields.Char(compute='_compute_a1_upper', store=True)

    @api.depends('a1')
    def _compute_a1_upper(self):
        for rec in self:
            rec.a1_upper = (rec.a1 or '').upper()

    @api.constrains('a1')
    def _check_a1_not_bad(self):
        for rec in self:
            if rec.a1 == 'BAD':
                raise ValidationError("a1 no puede ser 'BAD'")

    def set_a1(self):
        """Override the set_a1 method from Test1."""
        self.a1 = 'Set by test4'


class Test4Line(models.Model):
    """Modelo regular (no poly) con un m2o a un modelo poly (test.test4).
    Cubre one2many sobre poly y FK desde un modelo regular hacia un registro poly."""
    _name = 'test.test4.line'
    _description = 'Test4 Line'

    name = fields.Char('Name')
    parent_id = fields.Many2one('test.test4', string='Parent', ondelete='cascade')
