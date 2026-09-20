# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class NumaObservabilityProbe(models.Model):
    """A model that exists only to carry the observability mixin in tests."""
    _name = 'numa.observability.probe'
    _inherit = ['real.time.observability.mixin']
    _description = "Observability Probe"

    name = fields.Char(string="Name", required=True)
    state = fields.Selection([('draft', "Draft"), ('done', "Done")],
                             string="State", default='draft')
