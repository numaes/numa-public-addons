# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import fields, Command
from odoo.tests import Form, HttpCase, new_test_user
from odoo.tools.float_utils import float_round


from odoo.fields import Command

from odoo.addons.base.tests.common import TransactionCase


import logging

_logger = logging.getLogger(__name__)


class PolyTestCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        _logger.info(f'PolyTestCommon Setup')
        super().setUpClass()

