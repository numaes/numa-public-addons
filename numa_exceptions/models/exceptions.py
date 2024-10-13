# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems.
#  
#    Copyright (C) 2013 NUMA Extreme Systems (<http:www.numaes.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import models, fields, api, _, registry, exceptions
from odoo.exceptions import UserError, ValidationError, RedirectWarning
from odoo import SUPERUSER_ID
from odoo.loglevels import exception_to_unicode
from odoo.http import request, Response, ROUTING_KEYS, Stream

import odoo
import werkzeug
import werkzeug.exceptions
import werkzeug.routing
import werkzeug.utils

from odoo.http import SessionExpiredException

import datetime
import sys
import inspect
from odoo.osv import expression


import logging
_logger = logging.getLogger(__name__)

DT_FORMAT = "%Y-%m-%d %H:%M:%S"


class VariableValue(models.Model):
    _name = "base.variable_value"
    _description = "Exceptions: Variable Value"

    frame = fields.Many2one(comodel_name='base.frame', string='Frame', ondelete="cascade")
    sequence = fields.Integer(string='Sequence')
    name = fields.Char(string='Name', readonly=True)
    value = fields.Text(string='Value', readonly=True)


class Frame(models.Model):
    _name = "base.frame"
    _description = "Exceptions: Call Frame"

    gexception = fields.Many2one(comodel_name='base.general_exception', string='Exception', ondelete="cascade")
    src_code = fields.Text(string='Source code', readonly=True)
    line_number = fields.Integer(string='Line number', readonly=True)
    file_name = fields.Char(string='File name', readonly=True)
    locals = fields.One2many(comodel_name='base.variable_value',
                             inverse_name='frame',
                             string='Local variables',
                             readonly=True)

    @api.depends('file_name', 'line_number')
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s %d" % (record.file_name, record.line_number)

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=80, order=None):
        domain = domain or []
        if operator != 'ilike' or (name or '').strip():
            name_domain = ['|', ('file_name', operator, name), ('line_number', operator, name)]
            domain = expression.AND([name_domain, domain])
        return self._search(domain, limit=limit, order=order)

class GeneralException (models.Model):
    _name = "base.general_exception"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Exceptions: Exception Log"
    _order = "timestamp desc"

    name = fields.Char(string='Identification', readonly=True)
    service = fields.Char(string='Service', readonly=True)
    exception = fields.Text(string='Exception', readonly=True)
    method = fields.Char(string='Method', readonly=True)
    params = fields.Text(string='Params', readonly=True)
    timestamp = fields.Datetime(string='Timestamp', readonly=True)
    do_not_purge = fields.Boolean(string='Do not purge?', readonly=True)
    user = fields.Many2one(comodel_name='res.users', string='User', readonly=True, ondelete='set null')
    frames = fields.One2many(comodel_name='base.frame', inverse_name='gexception', string='Frames', readonly=True)
    frames_count = fields.Integer(string='Frames Count', compute='_compute_frames_count', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals = vals or {}
            vals['name'] = self.env['ir.sequence'].next_by_code('base.general_exception') or '/'
            vals['timestamp'] = fields.Datetime.now()
        return super(GeneralException, self).create(vals_list)

    def _compute_frames_count(self):
        for record in self:
            record.frames_count = len(record.frames) if record.frames else 0

    def action_frames(self):
        self.ensure_one()

        ge = self
        return {
            'name': _("Frames"),
            'view_mode': 'tree,form',
            'view_type': 'form',
            'res_model': 'base.frame',
            'type': 'ir.actions.act_window',
            'domain': [('gexception', '=', ge.id)],
            'nodestroy': True,
        }
        
    def action_clean(self):
        now = datetime.datetime.utcnow()
        one_month_before_dt = now - datetime.timedelta(days=30)
        one_month_before = one_month_before_dt.strftime(DT_FORMAT)
        to_delete = super(GeneralException, self).search(
            [('do_not_purge', '!=', True),
             ('timestamp', '<', one_month_before)
             ]
        )
        _logger.info("Cleaning old exceptions. %d eligible exceptions found" % len(to_delete))
        if to_delete:
            to_delete.unlink()
        
        return True

    @api.model
    def new_exception(self, e, service_name='unknown', method='unknown', params=None):
        register_exception(service_name, method, params, self.env.cr.dbname, self.env.user.id, e)


def register_exception(service_name, method, params, db, uid, e):
    if not db:
        return None

    db_registry = odoo.modules.registry.Registry(db)

    if not db_registry:
        return None

    if "base.general_exception" in db_registry:
        with db_registry.cursor() as new_cr:
            env = api.Environment(new_cr, SUPERUSER_ID, {})
            ge_obj = env["base.general_exception"]

            tb = sys.exc_info()[2]
            if tb:
                frames = []
                count = 0
                while tb:
                    frame = tb.tb_frame
                    local_vars = []
                    output = '<pre>\n'
                    try:
                        if count >= 0:
                            local_vars = [(0, 0, {'name': str(k), 'value': str(v)})
                                          for k, v in frame.f_locals.items()]
                            local_vars.sort(key=lambda x: x[2]['name'])
                            seq = 1
                            for lv in local_vars:
                                lv[2]['sequence'] = seq
                                seq += 1
                            lines, lineno = inspect.getsourcelines(frame)
                            for line in lines:
                                if (frame.f_lineno - 10) < lineno < (frame.f_lineno + 10):
                                    if frame.f_lineno == lineno:
                                        fmt = '</pre><b><pre>%5d: %s</pre></b><pre>'
                                    else:
                                        fmt = '%5d: %s'
                                    output += fmt % (lineno, line)
                                lineno += 1
                    except Exception as process_exception:
                        output += "\nEXCEPTION DURING PROCESSING: %s" % exception_to_unicode(process_exception)

                    output += '</pre>'
                    frames.append(
                        (0, 0, {'file_name': frame.f_code.co_filename,
                                'line_number': frame.f_lineno,
                                'src_code': output,
                                'locals': local_vars}))
                    count += 1
                    tb = tb.tb_next
                frames.reverse()

                def get_exception_chain(exc):
                    if exc.__cause__:
                        return "%s\n\nCaused by:\n%s" % (str(exc), get_exception_chain(exc.__cause__))
                    return str(exc)

                exc_description = get_exception_chain(e)

                vals = {
                    'service': service_name,
                    'exception': exc_description,
                    'method': method,
                    'params': params or [],
                    'do_not_purge': False,
                    'user': uid,
                    'frames': frames,
                }
                _logger.error("About to log exception [%s], on service [%s, %s, %s]" %
                              (exc_description, service_name, method, params))
                try:
                    ge = ge_obj.sudo().create(vals)
                    ename = ge.name
                    return ename
                except Exception as loggingException:
                    _logger.error("Error logging exception, exception [%s]" % loggingException)

    return None


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        try:
            return super(IrHttp, cls)._dispatch(endpoint)
        except Exception as e:
            ename = register_exception(
                'Endpoint %s' % request.httprequest,
                'IrHttp.dispatch',
                request.params,
                request.db or False,
                request.env.uid,
                e)

            if not isinstance(e, (
                    odoo.exceptions.RedirectWarning,
                    SessionExpiredException,
                    UserError,
                    werkzeug.exceptions.NotFound)):
                if ename:
                    e = UserError(_('System error %s. Get in touch with your System Admin') % ename)

            raise e


class IrCron(models.Model):
    _inherit = 'ir.cron'

    @api.model
    def _handle_callback_exception(self, cron_name, server_action_id, job_id, job_exception):
        model = 'CRON %s' % (cron_name or '<unknown>')
        method = None
        params = [server_action_id, job_id]
        db = self.env.cr.dbname
        uid = self.env.user.id

        register_exception(
            model,
            method,
            params,
            db,
            uid,
            job_exception)

        return super()._handle_callback_exception(cron_name, server_action_id, job_id, job_exception)

