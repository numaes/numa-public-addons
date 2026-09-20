# -*- coding: utf-8 -*-
"""
Shared base class for the numa_poly test suite.

The fixture models used to be declared here as well, and were copied to
``models/fixture_models.py`` without deleting the originals. Both copies then
registered the same six model names, and which one the registry ended up using
depended on import order — so a field added to the fixture could be missing from
the model the tests actually saw, while `ir_model_fields` reflected it. That is
how the same suite passed on `-u` and failed on `-i`.

A model belongs to a module: it lives under ``models/``, which owns it and
creates its table. Nothing but test cases is declared in ``tests/``.
"""
from odoo.tests.common import TransactionCase


class PolyTestCommon(TransactionCase):
    """Base TestCase for the numa_poly tests.

    ``test_structure.py`` imports it (`from .common import PolyTestCommon`) and it
    was missing, so that file could not be imported and had fallen out of
    ``tests/__init__``. It is a plain TransactionCase; each test does its own
    specific setUp.
    """
    pass
