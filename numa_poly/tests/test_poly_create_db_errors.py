# -*- coding: utf-8 -*-
"""
In create, what poly does before inserting into a non-polymorphic model does not hide database errors.

Syncing the table sequence sat inside ``except Exception: pass``. With the transaction already
aborted -a concurrency conflict that some other code had swallowed- the error slipped past and the
create failed on the next query with InFailedSqlTransaction, far from the cause: that is how it
showed up in prtest on 2026-09-10, in the bus.bus of /discuss/channel/mark_as_read. Reserving the
shared id had the same defect, with a log in between.
"""
from unittest.mock import patch

import psycopg2

from odoo.tests import tagged, TransactionCase

from ..models import poly as P

LOGGER = 'odoo.addons.numa_poly.models.poly'


@tagged('post_install', '-at_install')
class TestPolyCreateDatabaseErrors(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Model = self.env['res.partner.category']
        self.Clase = type(self.Model)
        self.assertFalse(P._poly_is_polymorphic(self.Model), 'the test needs a non-polymorphic model')

    def test_01_a_database_error_syncing_the_sequence_propagates(self):
        abortada = psycopg2.errors.InFailedSqlTransaction('current transaction is aborted')
        with patch.object(self.Clase, '_sync_table_id_sequence_once', side_effect=abortada):
            with self.assertRaises(psycopg2.errors.InFailedSqlTransaction):
                self.Model.create({'name': 'poly db error 1'})

    def test_02_any_other_error_syncing_the_sequence_is_still_tolerated(self):
        with patch.object(self.Clase, '_sync_table_id_sequence_once', side_effect=RuntimeError('no sequence')):
            self.assertTrue(self.Model.create({'name': 'poly db error 2'}))

    def test_03_a_database_error_reserving_the_id_propagates(self):
        conflicto = psycopg2.errors.SerializationFailure('could not serialize access')
        with patch.object(self.Clase, '_poly_reserve_base_ids', side_effect=conflicto):
            with self.assertRaises(psycopg2.errors.SerializationFailure):
                self.Model.create({'name': 'poly db error 3'})

    def test_04_any_other_error_reserving_the_id_is_logged_and_tolerated(self):
        with patch.object(self.Clase, '_poly_reserve_base_ids', side_effect=RuntimeError('odd hierarchy')), \
                self.assertLogs(LOGGER, level='ERROR') as logs:
            self.assertTrue(self.Model.create({'name': 'poly db error 4'}))
        self.assertTrue(any('could not reserve a shared id' in linea for linea in logs.output), logs.output)
