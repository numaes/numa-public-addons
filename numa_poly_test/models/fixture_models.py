# -*- coding: utf-8 -*-
"""
Fixture models for the numa_poly behavior/API tests.

They used to live in tests/common.py, but models defined under tests/ load too late
and are NOT registered -> test_advanced_api / test_orm_behavior failed with
`KeyError: 'test.poly.child.a'`. They are moved to models/ (like test.test1..4) so that
they get registered with the module.
"""

from odoo import fields, models
from odoo.addons.numa_poly.models.poly import PolyModel


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
    """Business model injecting two behaviors (diamond: 2 _depend_models)."""
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
    # A relational field on the base. Concrete models must reach it through the
    # link field, without a column or a relation table of their own: the reported
    # failure was a many2many inherited from a polymorphic base that Odoo's
    # incremental loader had injected as stored on the concrete model, so reading
    # it looked for a table that does not exist.
    base_partner_ids = fields.Many2many('res.partner', string='Base Partners')


class TestPolyChildA(PolyModel):
    """Concrete model inheriting from TestPolyBase."""
    _name = 'test.poly.child.a'
    _description = 'Test Poly Child A'
    _depend_models = {
        'test.poly.base': 'base_id',
    }

    child_a_field = fields.Char(string='Child A Field')
    # `fields.Reference` subclasses `fields.Selection`, which is why the guard
    # against cross-model Selection pollution used to drop every reference
    # written on a polymorphic model, with nothing but a log line to say so.
    ref_field = fields.Reference(
        selection=[('res.partner', 'Partner')], string='Reference Field')


class TestPolyChildB(PolyModel):
    """Another concrete model inheriting from TestPolyBase."""
    _name = 'test.poly.child.b'
    _description = 'Test Poly Child B'
    _depend_models = {
        'test.poly.base': 'base_id',
    }

    child_b_field = fields.Char(string='Child B Field')


class TestPlainDelegateParent(models.Model):
    """Plain (non-polymorphic) model, parent of an ``_inherits``."""
    _name = 'test.plain.delegate.parent'
    _description = 'Test Plain Delegate Parent'

    name = fields.Char(string='Name')


class TestPlainDelegateChild(models.Model):
    """Plain (non-polymorphic) model with a properly declared ``_inherits``.

    numa_poly replaces Odoo's ``_inherits`` check for every model; this fixture verifies
    that nothing changes for a plain model whose link field is declared.
    """
    _name = 'test.plain.delegate.child'
    _description = 'Test Plain Delegate Child'
    _inherits = {'test.plain.delegate.parent': 'parent_id'}

    parent_id = fields.Many2one('test.plain.delegate.parent', required=True, ondelete='cascade')
    code = fields.Char(string='Code')


class TestPolyMixin(models.AbstractModel):
    """Mixin with its own fields, to tell apart what belongs to the base from
    what the base inherits.

    numa_poly redirects the base's fields to its row with ``related``. A field
    the base receives from a mixin is not base data: it reaches the concrete
    model through that same ``_inherit`` and redirecting it adds nothing. Worse:
    the set depended on whether the base's registry class was already built when
    the contribution ran, so the same code produced a different model depending
    on the build order.
    """
    _name = 'test.poly.mixin'
    _description = 'Test Poly Mixin'

    mixin_field = fields.Char(string='Mixin Field')
    mixin_computed = fields.Char(string='Mixin Computed', compute='_compute_mixin_computed')

    def _compute_mixin_computed(self):
        for registro in self:
            registro.mixin_computed = 'computed by the mixin'


class TestPolyMixedBase(PolyModel):
    """Polymorphic base that also inherits a mixin."""
    _name = 'test.poly.mixed.base'
    _description = 'Test Poly Mixed Base'
    _inherit = ['test.poly.mixin']
    _depend_models = {}

    dato_de_la_base = fields.Char(string='Base Data')


class TestPolyMixedChild(PolyModel):
    """Concrete model over a base that inherits a mixin."""
    _name = 'test.poly.mixed.child'
    _description = 'Test Poly Mixed Child'
    _depend_models = {
        'test.poly.mixed.base': 'mixed_base_id',
    }

    dato_del_concreto = fields.Char(string='Concrete Data')
