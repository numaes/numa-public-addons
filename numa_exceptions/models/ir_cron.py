# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from odoo import models

from .exceptions import register_exception


class IrCron(models.Model):
    _inherit = 'ir.cron'

    def _callback(self, cron_name, server_action_id):
        """Log the failures of a scheduled action before letting them through."""
        try:
            return super()._callback(cron_name, server_action_id)
        except Exception as error:
            register_exception(
                'CRON %s' % (cron_name or '<unknown>'),
                'ir.cron._callback',
                {'cron_name': cron_name, 'server_action_id': server_action_id},
                self.env.cr.dbname,
                self.env.uid,
                error,
            )
            raise
