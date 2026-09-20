# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

import logging
import threading

import werkzeug.exceptions

from odoo import SUPERUSER_ID, models
from odoo.exceptions import AccessDenied, AccessError, RedirectWarning, UserError, ValidationError
from odoo.http import request, request_var
from odoo.http.session import SessionExpiredException

from .exceptions import register_exception

_logger = logging.getLogger(__name__)

# Exceptions that carry a business meaning or drive the request flow: they are
# a normal outcome of a request and must reach the user untouched.
BUSINESS_EXCEPTIONS = (
    AccessDenied,
    AccessError,
    RedirectWarning,
    SessionExpiredException,
    UserError,
    ValidationError,
    werkzeug.exceptions.HTTPException,
)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _handle_error(cls, exception):
        """Log unhandled request exceptions and hand the user a reference.

        Every dispatcher (HTTP, JSON-RPC and JSON2) funnels its errors through
        ``ir.http._handle_error``, so this single override covers them all.
        """
        if cls._should_log_exception(exception):
            reference = cls._register_request_exception(exception)
            if reference:
                exception = UserError(request.env._(
                    "System error %s. Get in touch with your System Admin.", reference))
        return super()._handle_error(exception)

    @classmethod
    def _should_log_exception(cls, exception):
        """Tell whether an exception is worth a log entry.

        Business and flow-control exceptions are the expected outcome of a
        request: logging them would drown the real failures.
        """
        return not isinstance(exception, BUSINESS_EXCEPTIONS)

    @classmethod
    def _register_request_exception(cls, exception):
        """Log a request exception, returning its reference or None.

        Wrapped so that a failure of the logging itself never replaces the
        error the user was about to be shown.
        """
        try:
            req = request_var.get(None)
            service = 'Endpoint unknown'
            params = {}
            db = False
            uid = SUPERUSER_ID
            if req is not None:
                service = 'Endpoint %s' % (getattr(req, 'httprequest', None) or 'unknown')
                params = getattr(req, 'params', None) or {}
                db = getattr(req, 'db', False)
                env = getattr(req, 'env', None)
                uid = env.uid if env is not None else SUPERUSER_ID
            if not db:
                db = getattr(threading.current_thread(), 'dbname', False)
            return register_exception(service, 'ir.http._handle_error', params, db, uid, exception)
        except Exception:  # noqa: BLE001 - logging must never mask the served error
            _logger.error("Error while registering a request exception", exc_info=True)
            return None
