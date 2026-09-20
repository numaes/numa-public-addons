# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""Tests of the exception log models and of their access rights."""

from unittest.mock import patch

import werkzeug.exceptions

from odoo import fields
from odoo.addons.base.tests.common import BaseCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http.session import SessionExpiredException
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger

from ..models import ir_cron as ir_cron_module
from ..models import ir_http as ir_http_module
from ..models.base_general_exception import DEFAULT_RETENTION_DAYS, RETENTION_DAYS_PARAM


class ExceptionLogCommon(BaseCommon):
    _test_user_groups = ('base.group_user', 'base.group_system')

    def _log(self, **vals):
        return self.env['base.general_exception'].create({
            'service': 'test.service',
            'method': 'test_method',
            'exception': 'boom',
            **vals,
        })


class TestExceptionLog(ExceptionLogCommon):

    def test_create_assigns_a_reference_and_a_timestamp(self):
        before = fields.Datetime.now()
        record = self._log()

        self.assertTrue(record.name.startswith('EXC'), record.name)
        self.assertEqual(len(record.name), len('EXC') + 8)
        self.assertGreaterEqual(record.timestamp, before)

    def test_create_gives_each_record_its_own_reference(self):
        first, second = self._log(), self._log()

        self.assertNotEqual(first.name, second.name)

    def test_create_keeps_an_explicit_reference(self):
        record = self._log(name='EXC-IMPORTED')

        self.assertEqual(record.name, 'EXC-IMPORTED')

    def test_frames_count_follows_the_frames(self):
        record = self._log(frames=[
            (0, 0, {'file_name': '/tmp/a.py', 'line_number': 1}),
            (0, 0, {'file_name': '/tmp/b.py', 'line_number': 2}),
        ])

        self.assertEqual(record.frames_count, 2)
        record.frames[0].unlink()
        self.assertEqual(record.frames_count, 1)

    def test_action_frames_targets_this_exception_only(self):
        record = self._log()
        other = self._log()

        action = record.action_frames()

        self.assertEqual(action['res_model'], 'base.frame')
        self.assertEqual(action['domain'], [('gexception', '=', record.id)])
        self.assertNotEqual(record.id, other.id)

    def test_unlinking_an_exception_unlinks_its_frames_and_locals(self):
        record = self._log(frames=[(0, 0, {
            'file_name': '/tmp/a.py',
            'line_number': 1,
            'locals': [(0, 0, {'sequence': 1, 'name': 'x', 'value': '1'})],
        })])
        frame_id = record.frames.id
        value_id = record.frames.locals.id

        record.unlink()

        self.assertFalse(self.env['base.frame'].browse(frame_id).exists())
        self.assertFalse(self.env['base.variable_value'].browse(value_id).exists())


class TestExceptionPurge(ExceptionLogCommon):

    def _aged(self, days, **vals):
        return self._log(
            timestamp=fields.Datetime.subtract(fields.Datetime.now(), days=days), **vals)

    def test_purge_removes_records_past_the_retention_period(self):
        old = self._aged(DEFAULT_RETENTION_DAYS + 1)
        recent = self._aged(DEFAULT_RETENTION_DAYS - 1)

        self.env['base.general_exception'].action_clean()

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_purge_keeps_records_flagged_do_not_purge(self):
        kept = self._aged(DEFAULT_RETENTION_DAYS + 10, do_not_purge=True)

        self.env['base.general_exception'].action_clean()

        self.assertTrue(kept.exists())

    def test_purge_honours_the_retention_parameter(self):
        self.env['ir.config_parameter'].sudo().set_int(RETENTION_DAYS_PARAM, 2)
        old = self._aged(3)
        recent = self._aged(1)

        self.env['base.general_exception'].action_clean()

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_purge_is_disabled_by_a_zero_retention(self):
        self.env['ir.config_parameter'].sudo().set_int(RETENTION_DAYS_PARAM, 0)
        old = self._aged(DEFAULT_RETENTION_DAYS + 100)

        self.env['base.general_exception'].action_clean()

        self.assertTrue(old.exists())


class TestFrame(ExceptionLogCommon):

    def setUp(self):
        super().setUp()
        self.exception = self._log()
        self.frame = self.env['base.frame'].create({
            'gexception': self.exception.id,
            'file_name': '/opt/odoo/addons/numa_exceptions/models/exceptions.py',
            'line_number': 42,
        })

    def test_display_name_shows_file_and_line(self):
        self.assertEqual(
            self.frame.display_name,
            '/opt/odoo/addons/numa_exceptions/models/exceptions.py 42')

    def test_search_by_file_name(self):
        found = self.env['base.frame'].name_search('numa_exceptions/models')

        self.assertIn(self.frame.id, [record_id for record_id, _name in found])

    def test_search_by_line_number(self):
        found = self.env['base.frame'].name_search('42')

        self.assertIn(self.frame.id, [record_id for record_id, _name in found])

    def test_search_by_line_number_does_not_match_another_line(self):
        found = self.env['base.frame'].name_search('43')

        self.assertNotIn(self.frame.id, [record_id for record_id, _name in found])


class TestExceptionAccess(ExceptionLogCommon):

    def test_a_plain_employee_cannot_read_the_logs(self):
        record = self._log()
        employee = new_test_user(self.env, login='numa_exc_employee', groups='base.group_user')

        with self.assertRaises(AccessError):
            record.with_user(employee).read(['exception'])

    def test_a_plain_employee_cannot_read_the_captured_variables(self):
        record = self._log(frames=[(0, 0, {
            'file_name': '/tmp/a.py',
            'line_number': 1,
            'locals': [(0, 0, {'sequence': 1, 'name': 'x', 'value': '1'})],
        })])
        employee = new_test_user(self.env, login='numa_exc_employee2', groups='base.group_user')

        with self.assertRaises(AccessError):
            record.frames.locals.with_user(employee).read(['value'])

    def test_the_system_administrator_can_read_the_logs(self):
        record = self._log()

        self.assertEqual(record.with_user(self._test_user).exception, 'boom')


class TestRequestHook(ExceptionLogCommon):
    """The classification and the logging done by ``ir.http._handle_error``."""

    def test_business_exceptions_are_not_logged(self):
        ir_http = self.env['ir.http']

        self.assertFalse(ir_http._should_log_exception(UserError("wrong input")))
        self.assertFalse(ir_http._should_log_exception(ValidationError("invalid")))
        self.assertFalse(ir_http._should_log_exception(AccessError("denied")))
        self.assertFalse(ir_http._should_log_exception(werkzeug.exceptions.NotFound()))
        self.assertFalse(ir_http._should_log_exception(SessionExpiredException()))

    def test_unexpected_exceptions_are_logged(self):
        ir_http = self.env['ir.http']

        self.assertTrue(ir_http._should_log_exception(ValueError("boom")))
        self.assertTrue(ir_http._should_log_exception(KeyError('missing')))

    def test_registration_outside_a_request_still_reports_a_database(self):
        with patch.object(ir_http_module, 'register_exception',
                          return_value='EXC00000001') as registrar:
            reference = self.env['ir.http']._register_request_exception(ValueError("boom"))

        self.assertEqual(reference, 'EXC00000001')
        service, method, _params, db, _uid, error = registrar.call_args.args
        self.assertEqual(service, 'Endpoint unknown')
        self.assertEqual(method, 'ir.http._handle_error')
        self.assertEqual(db, self.env.cr.dbname, "falls back to the thread database")
        self.assertIsInstance(error, ValueError)

    def test_a_failing_registration_does_not_break_the_response(self):
        with patch.object(ir_http_module, 'register_exception',
                          side_effect=RuntimeError("logging is down")):
            with mute_logger('odoo.addons.numa_exceptions.models.ir_http'):
                reference = self.env['ir.http']._register_request_exception(ValueError("boom"))

        self.assertIsNone(reference)


class TestCronHook(ExceptionLogCommon):
    """``ir.cron._callback`` logs a failing scheduled action and re-raises."""

    def _failing_cron(self):
        action = self.env['ir.actions.server'].create({
            'name': 'numa_exceptions failing action',
            'model_id': self.env['ir.model']._get_id('ir.cron'),
            'state': 'code',
            # safe_eval has no builtins to raise with, so provoke the error
            'code': 'record = 1 / 0',
        })
        return self.env['ir.cron'].create({
            'name': 'numa_exceptions failing cron',
            'ir_actions_server_id': action.id,
            'interval_number': 1,
            'interval_type': 'days',
            'active': False,
        })

    def test_a_failing_cron_is_logged_and_the_error_propagates(self):
        cron = self._failing_cron()
        # ir.cron._callback rolls back before re-raising, which a test cursor
        # refuses; the rollback is not what this test is about.
        self.patch(self.env.cr, 'rollback', lambda: None)

        with patch.object(ir_cron_module, 'register_exception',
                          return_value='EXC00000002') as registrar:
            with self.assertRaises(ZeroDivisionError):
                cron._callback(cron.name, cron.ir_actions_server_id.id)

        service, method, params, db, uid, error = registrar.call_args.args
        self.assertEqual(service, 'CRON numa_exceptions failing cron')
        self.assertEqual(method, 'ir.cron._callback')
        self.assertEqual(params['server_action_id'], cron.ir_actions_server_id.id)
        self.assertEqual(db, self.env.cr.dbname)
        self.assertEqual(uid, self.env.uid)
        self.assertIn('division by zero', str(error))
