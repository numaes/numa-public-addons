# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.fields import Domain


class BaseFrame(models.Model):
    """A single entry of an execution stack trace.

    Holds the file, the line number, the surrounding source code and the local
    variables captured when the exception crossed this frame.
    """
    _name = 'base.frame'
    _description = "Exceptions: Call Frame"
    _order = 'gexception, id'
    _rec_names_search = ('file_name',)

    gexception = fields.Many2one(
        comodel_name='base.general_exception', string="Exception", ondelete='cascade', index=True,
        help="Related exception log")
    src_code = fields.Html(string="Source code", readonly=True,
                           help="HTML formatted source code snippet")
    line_number = fields.Integer(string="Line number", readonly=True,
                                 help="Line number where the exception occurred")
    file_name = fields.Char(string="File name", readonly=True,
                            help="Absolute path to the source file")
    locals = fields.One2many(
        comodel_name='base.variable_value', inverse_name='frame', string="Local variables",
        readonly=True, help="List of local variables captured at this frame")

    @api.depends('file_name', 'line_number')
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s %s" % (record.file_name or '', record.line_number)

    @api.model
    def _search_display_name(self, operator, value):
        """Let a frame be found by its file name or by its line number."""
        domains = [Domain('file_name', operator, value)]
        if isinstance(value, str) and value.isdigit():
            if operator.endswith('like'):
                # 'ilike' against an integer column: fall back to equality
                number_operator = '!=' if operator in Domain.NEGATIVE_OPERATORS else '='
            else:
                number_operator = operator
            domains.append(Domain('line_number', number_operator, int(value)))
        aggregator = Domain.AND if operator in Domain.NEGATIVE_OPERATORS else Domain.OR
        return aggregator(domains)
