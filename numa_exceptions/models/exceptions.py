# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems.
#
#    Copyright (C) 2013 NUMA Extreme Systems (<http:www.numaes.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
"""Capture of an exception and its call stack, independent of the ORM.

The module is split in two halves on purpose:

* ``build_exception_vals`` and the helpers it uses are pure functions. They
  turn a traceback into the values of a ``base.general_exception`` record and
  can be exercised without a database.
* ``register_exception`` is the only part that touches the database. It opens
  its own cursor so that the log survives the rollback of the transaction that
  failed.
"""

# Standard library
import functools
import inspect
import json
import logging
import sys
import threading

# Third-party
from markupsafe import Markup, escape

# Odoo
from odoo import Command, SUPERUSER_ID, api
from odoo.loglevels import exception_to_unicode
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

# Maximum number of frames to process in a stack trace (prevents memory issues)
MAX_STACK_FRAMES = 100

# Maximum length of the string representation of a single local variable
MAX_VALUE_LENGTH = 1000

# Maximum length of the serialized parameters of the failing call
MAX_PARAMS_LENGTH = 10000

# Number of source lines shown before and after the failing line
SOURCE_CONTEXT_LINES = 10

# Keywords to filter from local variables (security: prevent logging sensitive data)
SENSITIVE_KEYWORDS = (
    'password', 'passwd', 'pwd', 'token', 'secret', 'key', 'api_key',
    'access_token', 'auth', 'credential', 'private', 'sensitive',
)

FILTERED_PLACEHOLDER = '<FILTERED - sensitive information>'
UNSERIALIZABLE_PLACEHOLDER = '<Cannot serialize>'
TRUNCATION_SUFFIX = '... (truncated)'

EXCEPTION_MODEL = 'base.general_exception'


def is_sensitive(name):
    """Tell whether a variable name looks like it holds a secret.

    :param name: variable name as found in a frame
    :return: True when the name must not be logged
    """
    lowered = str(name).lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


def format_value(value):
    """Render a local variable as a bounded, filtered string."""
    try:
        text = str(value)
    except Exception:  # noqa: BLE001 - any __str__ may raise, and must not break logging
        return UNSERIALIZABLE_PLACEHOLDER
    if len(text) > MAX_VALUE_LENGTH:
        text = text[:MAX_VALUE_LENGTH] + TRUNCATION_SUFFIX
    return text


def capture_locals(frame):
    """Build the ``base.variable_value`` commands for the locals of a frame.

    Names matching a sensitive keyword are replaced by a placeholder, and
    every value is truncated to ``MAX_VALUE_LENGTH``.

    :param frame: a Python frame object
    :return: a list of ``Command.create`` commands, sorted by variable name
    """
    try:
        frame_locals = dict(frame.f_locals)
    except Exception:  # noqa: BLE001 - reading a live frame must not break logging
        return []

    values = []
    for name, value in frame_locals.items():
        name = str(name)
        values.append((name, FILTERED_PLACEHOLDER if is_sensitive(name) else format_value(value)))
    values.sort(key=lambda item: item[0])
    return [
        Command.create({'sequence': sequence, 'name': name, 'value': value})
        for sequence, (name, value) in enumerate(values, start=1)
    ]


def capture_source(frame):
    """Render the source lines around the failing line of a frame as HTML.

    :param frame: a Python frame object
    :return: an HTML ``<pre>`` block, escaped, with the failing line in bold
    """
    try:
        lines, first_line_number = inspect.getsourcelines(frame)
    except Exception as error:  # noqa: BLE001 - source may be unavailable (C code, exec, ...)
        return Markup("<pre>\n%s</pre>\n") % (
            "SOURCE NOT AVAILABLE: %s" % exception_to_unicode(error)
        )

    rendered = []
    for offset, line in enumerate(lines):
        line_number = first_line_number + offset
        if not (frame.f_lineno - SOURCE_CONTEXT_LINES) < line_number < (frame.f_lineno + SOURCE_CONTEXT_LINES):
            continue
        text = escape("%5d: %s" % (line_number, line))
        rendered.append(Markup("<b>%s</b>") % text if line_number == frame.f_lineno else text)

    return Markup("<pre>\n%s</pre>\n") % Markup("").join(rendered)


def capture_frames(tb):
    """Build the ``base.frame`` commands for a traceback.

    Frames are stored innermost first, which is where the reader starts. A
    stack deeper than ``MAX_STACK_FRAMES`` keeps its innermost frames, the
    ones that say where it broke, and drops the callers above them.

    :param tb: a traceback object, or None
    :return: a list of ``Command.create`` commands
    """
    frames = []
    while tb:
        frames.append(tb.tb_frame)
        tb = tb.tb_next
    frames.reverse()
    return [
        Command.create({
            'file_name': frame.f_code.co_filename,
            'line_number': frame.f_lineno,
            'src_code': capture_source(frame),
            'locals': capture_locals(frame),
        })
        for frame in frames[:MAX_STACK_FRAMES]
    ]


def format_exception_chain(e):
    """Render an exception and the chain of exceptions that caused it."""
    messages = []
    seen = set()
    current = e
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(exception_to_unicode(current))
        current = current.__cause__
    return "\n\nCaused by:\n".join(messages)


def serialize_params(params):
    """Render the parameters of the failing call as a bounded string."""
    if params is None:
        return '{}'
    try:
        if isinstance(params, (dict, list)):
            text = json.dumps(params, default=str, ensure_ascii=False)
        else:
            text = str(params)
    except Exception as error:  # noqa: BLE001 - serialization must never break logging
        _logger.warning("Error serializing params in register_exception: %s", error)
        return '<Error serializing params: %s>' % exception_to_unicode(error)
    if len(text) > MAX_PARAMS_LENGTH:
        text = text[:MAX_PARAMS_LENGTH] + TRUNCATION_SUFFIX
    return text


def build_exception_vals(service_name, method, params, uid, e, tb=None):
    """Turn an exception into the values of a ``base.general_exception`` record.

    This function touches no cursor and no registry, so it can be called and
    tested outside of any transaction.

    :param service_name: string identifying the origin (e.g. 'sale.order')
    :param method: method name where the error occurred
    :param params: arguments passed to the method (dict, list, or any object)
    :param uid: id of the user who triggered the exception, or False
    :param e: the exception instance
    :param tb: traceback to walk; defaults to the one carried by ``e``, then
        to the one currently being handled. Pass a falsy value to skip the stack.
    :return: a dict of values ready for ``create``
    """
    if tb is None:
        tb = e.__traceback__ or sys.exc_info()[2]
    return {
        'service': service_name or 'unknown',
        'exception': format_exception_chain(e),
        'method': method or 'unknown',
        'params': serialize_params(params),
        'do_not_purge': False,
        'user': uid or False,
        'frames': capture_frames(tb),
    }


def register_exception(service_name, method, params, db, uid, e):
    """Log an exception into the database.

    A new cursor is opened so that the log is persisted even when the main
    transaction fails and is rolled back.

    :param service_name: string identifying the origin (e.g. 'sale.order')
    :param method: method name where the error occurred
    :param params: arguments passed to the method (dict, list, or any object)
    :param db: database name; falls back to the one of the current thread
    :param uid: id of the user who triggered the exception
    :param e: the exception instance
    :return: the unique exception reference, or None when nothing was logged.
        This function is designed never to raise, even if logging fails.
    """
    if not service_name:
        _logger.warning("register_exception called with empty service_name, using 'unknown'")
        service_name = 'unknown'

    if not db:
        db = getattr(threading.current_thread(), 'dbname', False)
        if not db:
            _logger.debug("register_exception called with empty db, skipping logging")
            return None

    try:
        db_registry = Registry(db)
    except Exception as registry_error:  # noqa: BLE001 - a broken registry must not mask the original error
        _logger.error("Error accessing registry for database '%s' in register_exception: %s",
                      db, registry_error)
        return None

    if EXCEPTION_MODEL not in db_registry:
        _logger.debug("Model '%s' not found in registry for database '%s'", EXCEPTION_MODEL, db)
        return None

    try:
        vals = build_exception_vals(service_name, method, params, uid, e)
        _logger.info("About to log exception [%s], on service [%s, %s]",
                     vals['exception'], service_name, method)
        with db_registry.cursor() as new_cr:
            env = api.Environment(new_cr, SUPERUSER_ID, {})
            record = env[EXCEPTION_MODEL].create(vals)
            reference = record.name
            # Own cursor, own transaction: committing here is what makes the
            # log survive the rollback of the transaction that failed.
            new_cr.commit()
            return reference
    except Exception as logging_error:  # noqa: BLE001 - logging must never mask the original error
        _logger.error("Error logging an exception in database '%s': %s. Service: %s, Method: %s",
                      db, logging_error, service_name, method, exc_info=True)
        return None


def exception_managed(service_name=None):
    """Decorate a model method so that its failures are logged and re-raised.

    :param service_name: optional name for the service; defaults to the model name
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                register_exception(
                    service_name=service_name or getattr(self, '_name', 'UnknownService'),
                    method=func.__name__,
                    params={'args': args, 'kwargs': kwargs},
                    db=self.env.cr.dbname,
                    uid=self.env.uid,
                    e=e,
                )
                # Re-raise so that the standard Odoo error handling is not bypassed
                raise
        return wrapper
    return decorator
