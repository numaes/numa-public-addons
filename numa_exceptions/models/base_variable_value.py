# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class BaseVariableValue(models.Model):
    """Name and string representation of a local variable within a call frame."""
    _name = 'base.variable_value'
    _description = "Exceptions: Variable Value"
    _order = 'frame, sequence, id'

    frame = fields.Many2one(
        comodel_name='base.frame', string="Frame", ondelete='cascade', index=True,
        help="Related stack frame")
    sequence = fields.Integer(string="Sequence", help="Order of appearance in the frame")
    name = fields.Char(string="Name", readonly=True, help="Variable name")
    value = fields.Text(string="Value", readonly=True, help="Variable value (string representation)")
