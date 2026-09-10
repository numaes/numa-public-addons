# -*- coding: utf-8 -*-
"""
En create, lo que poly hace antes de insertar en un modelo no polimórfico no tapa errores de la base.

Sincronizar la secuencia de la tabla estaba en ``except Exception: pass``. Con la transacción ya
abortada —un conflicto de concurrencia que otro código había tragado— el error pasaba de largo y el
create fallaba en la consulta siguiente con InFailedSqlTransaction, lejos de la causa: así apareció
en prtest el 2026-09-10, en el bus.bus de /discuss/channel/mark_as_read. Reservar el id compartido
tenía el mismo defecto, con un log de por medio.
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
        self.assertFalse(P._poly_is_polymorphic(self.Model), 'la prueba necesita un modelo no polimórfico')

    def test_01_a_database_error_syncing_the_sequence_propagates(self):
        abortada = psycopg2.errors.InFailedSqlTransaction('current transaction is aborted')
        with patch.object(self.Clase, '_sync_table_id_sequence_once', side_effect=abortada):
            with self.assertRaises(psycopg2.errors.InFailedSqlTransaction):
                self.Model.create({'name': 'poly db error 1'})

    def test_02_any_other_error_syncing_the_sequence_is_still_tolerated(self):
        with patch.object(self.Clase, '_sync_table_id_sequence_once', side_effect=RuntimeError('sin secuencia')):
            self.assertTrue(self.Model.create({'name': 'poly db error 2'}))

    def test_03_a_database_error_reserving_the_id_propagates(self):
        conflicto = psycopg2.errors.SerializationFailure('could not serialize access')
        with patch.object(self.Clase, '_poly_reserve_base_ids', side_effect=conflicto):
            with self.assertRaises(psycopg2.errors.SerializationFailure):
                self.Model.create({'name': 'poly db error 3'})

    def test_04_any_other_error_reserving_the_id_is_logged_and_tolerated(self):
        with patch.object(self.Clase, '_poly_reserve_base_ids', side_effect=RuntimeError('jerarquía rara')), \
                self.assertLogs(LOGGER, level='ERROR') as logs:
            self.assertTrue(self.Model.create({'name': 'poly db error 4'}))
        self.assertTrue(any('could not reserve a shared id' in linea for linea in logs.output), logs.output)
