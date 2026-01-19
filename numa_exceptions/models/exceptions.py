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
import functools
from odoo.osv import expression


import logging
_logger = logging.getLogger(__name__)

DT_FORMAT = "%Y-%m-%d %H:%M:%S"

# Maximum number of frames to process in stack trace (prevents memory issues)
MAX_STACK_FRAMES = 100

# Keywords to filter from local variables (security: prevent logging sensitive data)
SENSITIVE_KEYWORDS = ['password', 'passwd', 'pwd', 'token', 'secret', 'key', 'api_key', 
                      'access_token', 'auth', 'credential', 'private', 'sensitive']


class VariableValue(models.Model):
    """
    Stores the name and string representation of a local variable within a call frame.
    """
    _name = "base.variable_value"
    _description = "Exceptions: Variable Value"

    frame = fields.Many2one(comodel_name='base.frame', string='Frame', ondelete="cascade", help="Related stack frame")
    sequence = fields.Integer(string='Sequence', help="Order of appearance in the frame")
    name = fields.Char(string='Name', readonly=True, help="Variable name")
    value = fields.Text(string='Value', readonly=True, help="Variable value (string representation)")


class Frame(models.Model):
    """
    Represents a single entry in the execution stack trace.
    Captures the file, line number, source code snippet, and local variables.
    """
    _name = "base.frame"
    _description = "Exceptions: Call Frame"

    gexception = fields.Many2one(comodel_name='base.general_exception', string='Exception', ondelete="cascade", help="Related exception log")
    src_code = fields.Html(string='Source code', readonly=True, help="HTML formatted source code snippet")
    line_number = fields.Integer(string='Line number', readonly=True, help="Line number where the exception occurred")
    file_name = fields.Char(string='File name', readonly=True, help="Absolute path to the source file")
    locals = fields.One2many(comodel_name='base.variable_value',
                             inverse_name='frame',
                             string='Local variables',
                             readonly=True,
                             help="List of local variables captured at this frame")

    @api.depends('file_name', 'line_number')
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s %d" % (record.file_name, record.line_number)

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=80, order=None):
        """
        Allows searching frames by file name or line number.
        """
        domain = domain or []
        if operator != 'ilike' or (name or '').strip():
            name_domain = ['|', ('file_name', operator, name), ('line_number', operator, name)]
            domain = expression.AND([name_domain, domain])
        return self._search(domain, limit=limit, order=order)

class GeneralException (models.Model):
    """
    Main model for storing exception logs.
    Aggregates error messages, stack frames, and execution metadata.
    """
    _name = "base.general_exception"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Exceptions: Exception Log"
    _order = "timestamp desc"

    name = fields.Char(string='Identification', readonly=True, help="Unique reference ID for the exception")
    service = fields.Char(string='Service', readonly=True, help="Name of the service or component where the error occurred")
    exception = fields.Text(string='Exception', readonly=True, help="Full exception message and cause chain")
    method = fields.Char(string='Method', readonly=True, help="Method name being executed")
    params = fields.Text(string='Params', readonly=True, help="Parameters passed to the method (string representation)")
    timestamp = fields.Datetime(string='Timestamp', readonly=True, help="When the exception occurred")
    do_not_purge = fields.Boolean(string='Do not purge?', readonly=True, help="If checked, this log will be excluded from the automatic purge")
    user = fields.Many2one(comodel_name='res.users', string='User', readonly=True, ondelete='set null', help="User who triggered the exception")
    frames = fields.One2many(comodel_name='base.frame', inverse_name='gexception', string='Frames', readonly=True, help="Ordered stack frames")
    frames_count = fields.Integer(string='Frames Count', compute='_compute_frames_count', readonly=True, help="Number of frames in the stack trace")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals = vals or {}
            # Generate a unique reference using a sequence
            vals['name'] = self.env['ir.sequence'].next_by_code('base.general_exception') or '/'
            vals['timestamp'] = fields.Datetime.now()
        return super(GeneralException, self).create(vals_list)

    def _compute_frames_count(self):
        for record in self:
            record.frames_count = len(record.frames) if record.frames else 0

    def action_frames(self):
        """
        Returns an action to view the frames associated with this exception.
        """
        self.ensure_one()

        ge = self
        return {
            'name': _("Frames"),
            'view_mode': 'list,form',
            'view_type': 'form',
            'res_model': 'base.frame',
            'type': 'ir.actions.act_window',
            'domain': [('gexception', '=', ge.id)],
            'nodestroy': True,
        }
        
    def action_clean(self):
        """
        Scheduled action to purge exception logs older than 30 days.
        Records marked with 'do_not_purge' are ignored.
        """
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
        """
        Entry point to manually register an exception from within a model.
        """
        register_exception(service_name, method, params, self.env.cr.dbname, self.env.user.id, e)


def exception_managed(service_name=None):
    """
    Decorator to automatically log exceptions in a method to the numa_exceptions system.
    It captures the execution context and calls register_exception before re-raising.

    :param service_name: Optional name for the service. Defaults to the model name.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                # Use provided service_name or fallback to model name
                s_name = service_name or getattr(self, '_name', 'UnknownService')

                # Extract Odoo environment details from 'self'
                # Works for both instance methods and @api.model methods
                db = self.env.cr.dbname
                uid = self.env.uid

                # Register the exception using the independent cursor logic
                register_exception(
                    service_name=s_name,
                    method=func.__name__,
                    params={'args': args, 'kwargs': kwargs},
                    db=db,
                    uid=uid,
                    e=e
                )
                # Re-raise to ensure the standard Odoo error handling is not bypassed
                raise e
        return wrapper
    return decorator


def register_exception(service_name, method, params, db, uid, e):
    """
    Global utility function to log an exception into the database.
    It opens a new database cursor to ensure the log is persisted even if the 
    main transaction fails and is rolled back.
    
    :param service_name: String identifying the origin (e.g., 'sale.order')
    :param method: Method name where the error occurred
    :param params: Arguments passed to the method
    :param db: Database name
    :param uid: User ID
    :param e: Exception instance
    :return: Unique exception reference string (name) or None
    """
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
                while tb and count < MAX_STACK_FRAMES:
                    frame = tb.tb_frame
                    local_vars = []
                    output = '<pre>\n'
                    try:
                        if count >= 0:
                            # Filter sensitive variables to prevent logging passwords, tokens, etc.
                            filtered_locals = {}
                            for k, v in frame.f_locals.items():
                                # Skip variables with sensitive keywords in their name
                                if any(keyword in k.lower() for keyword in SENSITIVE_KEYWORDS):
                                    filtered_locals[k] = '<FILTERED - sensitive information>'
                                else:
                                    try:
                                        # Truncate very long values to prevent excessive storage
                                        str_value = str(v)
                                        if len(str_value) > 1000:
                                            str_value = str_value[:1000] + '... (truncated)'
                                        filtered_locals[k] = str_value
                                    except Exception:
                                        filtered_locals[k] = '<Cannot serialize>'
                            
                            local_vars = [(0, 0, {'name': str(k), 'value': v})
                                          for k, v in filtered_locals.items()]
                            local_vars.sort(key=lambda x: x[2]['name'])
                            seq = 1
                            for lv in local_vars:
                                lv[2]['sequence'] = seq
                                seq += 1
                            lines, lineno = inspect.getsourcelines(frame)
                            for line in lines:
                                if (frame.f_lineno - 10) < lineno < (frame.f_lineno + 10):
                                    if frame.f_lineno == lineno:
                                        fmt = '<b>%5d: %s</b>'
                                    else:
                                        fmt = '%5d: %s'
                                    output += fmt % (lineno, line)
                                lineno += 1
                    except Exception as process_exception:
                        output += "\nEXCEPTION DURING PROCESSING: %s" % exception_to_unicode(process_exception)

                    output += '</pre>\n'
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
                    'user': uid if uid else False,
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
    """
    Extends Odoo's HTTP dispatcher to automatically capture and log 
    unhandled exceptions during web requests.
    """
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        try:
            return super(IrHttp, cls)._dispatch(endpoint)
        except Exception as e:
            _logger.exception(e)
            # Log the exception and get a unique reference ID
            # Validate request is available before accessing its attributes
            if request:
                ename = register_exception(
                    'Endpoint %s' % (request.httprequest if hasattr(request, 'httprequest') else 'Unknown'),
                    'IrHttp.dispatch',
                    request.params if hasattr(request, 'params') else {},
                    request.db if hasattr(request, 'db') else False,
                    request.env.uid if hasattr(request, 'env') else SUPERUSER_ID,
                    e)
            else:
                # Fallback for non-HTTP contexts (e.g., tests, cron)
                ename = register_exception(
                    'IrHttp.dispatch (no request context)',
                    'IrHttp.dispatch',
                    {},
                    False,
                    SUPERUSER_ID,
                    e)

            # For critical system errors, wrap the exception in a UserError 
            # with the reference ID to help the user report it.
            if not isinstance(e, (
                    odoo.exceptions.RedirectWarning,
                    SessionExpiredException,
                    UserError,
                    werkzeug.exceptions.NotFound)):
                if ename:
                    e = UserError(_('System error %s. Get in touch with your System Admin') % ename)

            raise e


class IrCron(models.Model):
    """
    Extends Odoo's Cron manager to automatically log exceptions 
    occurring during scheduled actions.
    """
    _inherit = 'ir.cron'

    @api.model
    def _handle_callback_exception(self, cron_name, server_action_id, job_id, job_exception):
        model = 'CRON %s' % (cron_name or '<unknown>')
        method = None
        params = [server_action_id, job_id]
        db = self.env.cr.dbname
        uid = self.env.user.id

        # Automatically log cron failures
        register_exception(
            model,
            method,
            params,
            db,
            uid,
            job_exception)

        return super()._handle_callback_exception(cron_name, server_action_id, job_id, job_exception)

