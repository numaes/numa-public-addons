# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""Tests of the capture helpers, which need no database."""

from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon
from odoo.tools import mute_logger

from ..models import exceptions as capture


def _raise_with_locals():
    """Raise from a frame holding a secret, a long value and a source '<'."""
    password = 'hunter2'
    api_key = 'ABC123'
    visible = 'kept'
    oversized = 'x' * (capture.MAX_VALUE_LENGTH + 50)
    if len(visible) < 100:
        raise ValueError("boom")


def _raise_deep(depth):
    if depth:
        return _raise_deep(depth - 1)
    raise RuntimeError("deep")


class Unprintable:
    def __str__(self):
        raise RuntimeError("cannot be printed")


class TestCapture(BaseCommon):

    def _caught(self, func, *args):
        """Return the exception raised by func, with its traceback attached."""
        try:
            func(*args)
        except Exception as error:
            return error
        self.fail("%s was expected to raise" % func.__name__)

    # -- locals ------------------------------------------------------------

    def test_sensitive_locals_are_filtered(self):
        error = self._caught(_raise_with_locals)
        vals = capture.build_exception_vals('svc', 'm', None, 1, error)
        innermost = vals['frames'][0][2]
        captured = {command[2]['name']: command[2]['value'] for command in innermost['locals']}

        self.assertEqual(captured['password'], capture.FILTERED_PLACEHOLDER)
        self.assertEqual(captured['api_key'], capture.FILTERED_PLACEHOLDER)
        self.assertEqual(captured['visible'], 'kept')

    def test_long_locals_are_truncated(self):
        error = self._caught(_raise_with_locals)
        vals = capture.build_exception_vals('svc', 'm', None, 1, error)
        captured = {c[2]['name']: c[2]['value'] for c in vals['frames'][0][2]['locals']}

        oversized = captured['oversized']
        self.assertTrue(oversized.endswith(capture.TRUNCATION_SUFFIX))
        self.assertEqual(len(oversized), capture.MAX_VALUE_LENGTH + len(capture.TRUNCATION_SUFFIX))

    def test_locals_are_sorted_and_numbered(self):
        error = self._caught(_raise_with_locals)
        vals = capture.build_exception_vals('svc', 'm', None, 1, error)
        commands = vals['frames'][0][2]['locals']

        names = [c[2]['name'] for c in commands]
        self.assertEqual(names, sorted(names))
        self.assertEqual([c[2]['sequence'] for c in commands], list(range(1, len(commands) + 1)))

    def test_unprintable_local_does_not_break_capture(self):
        self.assertEqual(capture.format_value(Unprintable()), capture.UNSERIALIZABLE_PLACEHOLDER)

    # -- source ------------------------------------------------------------

    def test_source_is_html_escaped(self):
        error = self._caught(_raise_with_locals)
        vals = capture.build_exception_vals('svc', 'm', None, 1, error)
        src_code = vals['frames'][0][2]['src_code']

        # The captured function holds 'if len(visible) < 100:'
        self.assertIn('&lt;', src_code)
        self.assertNotIn('visible) < 100', src_code)
        self.assertIn('<b>', src_code, "the failing line is highlighted")

    def test_source_unavailable_is_reported_not_raised(self):
        with patch.object(capture.inspect, 'getsourcelines', side_effect=OSError("no source")):
            error = self._caught(_raise_with_locals)
            vals = capture.build_exception_vals('svc', 'm', None, 1, error)

        self.assertIn('SOURCE NOT AVAILABLE', vals['frames'][0][2]['src_code'])

    # -- frames ------------------------------------------------------------

    def test_frames_are_innermost_first(self):
        error = self._caught(_raise_deep, 3)
        vals = capture.build_exception_vals('svc', 'm', None, 1, error)
        line_numbers = [c[2]['line_number'] for c in vals['frames']]

        raising_line = _raise_deep.__code__.co_firstlineno + 3
        self.assertEqual(line_numbers[0], raising_line,
                         "the frame that raised comes first")

    def test_frame_count_is_bounded_keeping_the_innermost_frames(self):
        error = self._caught(_raise_deep, capture.MAX_STACK_FRAMES + 50)
        vals = capture.build_exception_vals('svc', 'm', None, 1, error)

        self.assertEqual(len(vals['frames']), capture.MAX_STACK_FRAMES)
        self.assertEqual(vals['frames'][0][2]['line_number'],
                         _raise_deep.__code__.co_firstlineno + 3,
                         "a truncated stack keeps the frame that raised")

    def test_locals_of_an_unreadable_frame_are_skipped(self):
        class Hostile:
            @property
            def f_locals(self):
                raise RuntimeError("no locals for you")

        self.assertEqual(capture.capture_locals(Hostile()), [])

    def test_exception_without_traceback_still_logs(self):
        vals = capture.build_exception_vals('svc', 'm', None, 1, ValueError("no stack"), tb=False)

        self.assertEqual(vals['frames'], [])
        self.assertEqual(vals['exception'], "no stack")

    # -- exception chain ---------------------------------------------------

    def test_cause_chain_is_rendered(self):
        try:
            try:
                raise KeyError('root')
            except KeyError as root:
                raise ValueError("surface") from root
        except ValueError as error:
            rendered = capture.format_exception_chain(error)

        self.assertIn("surface", rendered)
        self.assertIn("Caused by:", rendered)
        self.assertIn("root", rendered)

    def test_cause_cycle_terminates(self):
        first = ValueError("first")
        second = ValueError("second")
        first.__cause__ = second
        second.__cause__ = first

        self.assertEqual(capture.format_exception_chain(first), "first\n\nCaused by:\nsecond")

    # -- params ------------------------------------------------------------

    def test_params_none_is_an_empty_mapping(self):
        self.assertEqual(capture.serialize_params(None), '{}')

    def test_params_dict_is_json(self):
        self.assertEqual(capture.serialize_params({'a': 1}), '{"a": 1}')

    def test_params_keeps_non_ascii_readable(self):
        self.assertEqual(capture.serialize_params({'name': 'año'}), '{"name": "año"}')

    def test_params_unserializable_member_falls_back_to_str(self):
        rendered = capture.serialize_params({'obj': object()})

        self.assertIn('object object at', rendered)

    def test_params_are_truncated(self):
        rendered = capture.serialize_params('y' * (capture.MAX_PARAMS_LENGTH + 100))

        self.assertTrue(rendered.endswith(capture.TRUNCATION_SUFFIX))
        self.assertEqual(len(rendered), capture.MAX_PARAMS_LENGTH + len(capture.TRUNCATION_SUFFIX))

    # -- register_exception guards ----------------------------------------

    @mute_logger('odoo.addons.numa_exceptions.models.exceptions')
    def test_register_exception_without_database_returns_none(self):
        with patch.object(capture.threading, 'current_thread', return_value=object()):
            self.assertIsNone(
                capture.register_exception('svc', 'm', None, False, 1, ValueError("x")))

    @mute_logger('odoo.addons.numa_exceptions.models.exceptions')
    def test_register_exception_without_model_returns_none(self):
        with patch.object(capture, 'Registry', return_value={}):
            self.assertIsNone(
                capture.register_exception('svc', 'm', None, 'somedb', 1, ValueError("x")))

    @mute_logger('odoo.addons.numa_exceptions.models.exceptions')
    def test_register_exception_never_raises(self):
        with patch.object(capture, 'Registry', side_effect=RuntimeError("registry down")):
            self.assertIsNone(
                capture.register_exception('svc', 'm', None, 'somedb', 1, ValueError("x")))

    @mute_logger('odoo.addons.numa_exceptions.models.exceptions')
    def test_register_exception_survives_a_broken_capture(self):
        with patch.object(capture, 'Registry', return_value={capture.EXCEPTION_MODEL: None}), \
             patch.object(capture, 'build_exception_vals', side_effect=RuntimeError("capture broke")):
            self.assertIsNone(
                capture.register_exception('svc', 'm', None, 'somedb', 1, ValueError("x")))

    # -- decorator ---------------------------------------------------------

    def test_exception_managed_logs_and_reraises(self):
        partners = self.env['res.partner']

        @capture.exception_managed()
        def failing(self):
            raise ValueError("decorated")

        with patch.object(capture, 'register_exception', return_value='EXC00000001') as registrar:
            with self.assertRaises(ValueError):
                failing(partners)

        self.assertEqual(registrar.call_count, 1)
        self.assertEqual(registrar.call_args.kwargs['service_name'], 'res.partner')
        self.assertEqual(registrar.call_args.kwargs['method'], 'failing')

    def test_exception_managed_passes_the_value_through(self):
        partners = self.env['res.partner']

        @capture.exception_managed('MyService')
        def succeeding(self):
            return 42

        self.assertEqual(succeeding(partners), 42)
