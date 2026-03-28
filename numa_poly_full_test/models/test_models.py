# -*- coding: utf-8 -*-
"""
Test models for numa_poly integration tests.

Hierarchy (diamond):

    poly.ft.base
   /            \\
poly.ft.alpha  poly.ft.beta
   \\            /
    poly.ft.top

poly.ft.base: root — no dependencies
poly.ft.alpha: depends on poly.ft.base (link: alpha_base_id)
poly.ft.beta:  depends on poly.ft.base (link: beta_base_id)
poly.ft.top:   depends on poly.ft.alpha (top_alpha_id) + poly.ft.beta (top_beta_id)
"""
from collections import OrderedDict
from odoo import models, fields


class PolyFtBase(models.Model):
    """Root model in the test hierarchy.  No polymorphic dependencies."""
    _name = 'poly.ft.base'
    _description = 'Poly Full Test — Base'
    _depend_models = OrderedDict()

    name = fields.Char('Name')
    value = fields.Integer('Value')

    def make_uppercase(self):
        """Uppercase the name field.  Overridable by child models."""
        self.name = (self.name or '').upper()


class PolyFtAlpha(models.Model):
    """Single-dependency model: depends on poly.ft.base."""
    _name = 'poly.ft.alpha'
    _description = 'Poly Full Test — Alpha'
    _depend_models = OrderedDict([('poly.ft.base', 'alpha_base_id')])

    alpha_note = fields.Char('Alpha Note')


class PolyFtBeta(models.Model):
    """Single-dependency model: depends on poly.ft.base (parallel to Alpha)."""
    _name = 'poly.ft.beta'
    _description = 'Poly Full Test — Beta'
    _depend_models = OrderedDict([('poly.ft.base', 'beta_base_id')])

    beta_count = fields.Integer('Beta Count')


class PolyFtTop(models.Model):
    """Diamond model: depends on both Alpha and Beta.

    Inherits name, value (via alpha/beta → base),
    alpha_note (via alpha), and beta_count (via beta).

    Overrides make_uppercase() to also append '_TOP' and set top_flag.
    """
    _name = 'poly.ft.top'
    _description = 'Poly Full Test — Top (diamond)'
    _depend_models = OrderedDict([
        ('poly.ft.alpha', 'top_alpha_id'),
        ('poly.ft.beta', 'top_beta_id'),
    ])

    top_flag = fields.Boolean('Top Flag')

    def make_uppercase(self):
        """Override: uppercase name (via super), append '_TOP', set top_flag."""
        super().make_uppercase()           # sets self.name = name.upper()
        self.name = (self.name or '') + '_TOP'
        self.top_flag = True
