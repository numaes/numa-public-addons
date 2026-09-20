# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models

from .exceptions import register_exception

_logger = logging.getLogger(__name__)

# Exception logs older than this many days are purged by the daily cron
DEFAULT_RETENTION_DAYS = 30

# Overrides DEFAULT_RETENTION_DAYS when set; 0 disables the purge
RETENTION_DAYS_PARAM = 'numa_exceptions.retention_days'


class BaseGeneralException(models.Model):
    """An exception captured by the system, with its stack and its context."""
    _name = 'base.general_exception'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Exceptions: Exception Log"
    _order = 'timestamp desc, id desc'

    name = fields.Char(string="Identification", readonly=True, index=True,
                       help="Unique reference ID for the exception")
    service = fields.Char(string="Service", readonly=True,
                          help="Name of the service or component where the error occurred")
    exception = fields.Text(string="Exception", readonly=True,
                            help="Full exception message and cause chain")
    method = fields.Char(string="Method", readonly=True, help="Method name being executed")
    params = fields.Text(string="Params", readonly=True,
                         help="Parameters passed to the method (string representation)")
    timestamp = fields.Datetime(string="Timestamp", readonly=True, index=True,
                                default=fields.Datetime.now,
                                help="When the exception occurred")
    do_not_purge = fields.Boolean(string="Do not purge?", readonly=True,
                                  help="If checked, this log is excluded from the automatic purge")
    user = fields.Many2one(comodel_name='res.users', string="User", readonly=True,
                           ondelete='set null', help="User who triggered the exception")
    frames = fields.One2many(comodel_name='base.frame', inverse_name='gexception',
                             string="Frames", readonly=True, help="Ordered stack frames")
    frames_count = fields.Integer(string="Frames Count", compute='_compute_frames_count',
                                  help="Number of frames in the stack trace")

    @api.depends('frames')
    def _compute_frames_count(self):
        for record in self:
            record.frames_count = len(record.frames)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('base.general_exception') or '/'
        return super().create(vals_list)

    def action_frames(self):
        """Open the stack frames of this exception."""
        self.ensure_one()
        return {
            'name': self.env._("Frames"),
            'type': 'ir.actions.act_window',
            'res_model': 'base.frame',
            'view_mode': 'list,form',
            'domain': [('gexception', '=', self.id)],
        }

    @api.model
    def action_clean(self):
        """Purge the exception logs older than the retention period.

        Records flagged with ``do_not_purge`` are kept. The retention period
        defaults to ``DEFAULT_RETENTION_DAYS`` and can be changed with the
        ``numa_exceptions.retention_days`` system parameter; setting it to 0
        disables the purge. This is the method run by the daily cron.
        """
        days = self.env['ir.config_parameter'].sudo().get_int(
            RETENTION_DAYS_PARAM, DEFAULT_RETENTION_DAYS)
        if days <= 0:
            _logger.info("Cleaning old exceptions is disabled (%s = %s)", RETENTION_DAYS_PARAM, days)
            return True

        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        to_delete = self.search([
            ('do_not_purge', '!=', True),
            ('timestamp', '<', limit),
        ])
        _logger.info("Cleaning old exceptions. %d eligible exceptions found", len(to_delete))
        to_delete.unlink()
        return True

    @api.model
    def new_exception(self, e, service_name='unknown', method='unknown', params=None):
        """Register an exception from within a model.

        :return: the unique exception reference, or None when nothing was logged
        """
        return register_exception(service_name, method, params,
                                  self.env.cr.dbname, self.env.uid, e)
