"""What the Master does with an incoming batch."""

import base64
import gzip
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import MasterSynchCase


@tagged('post_install', '-at_install')
class TestMasterEngine(MasterSynchCase):

    # ------------------------------------------------------------------
    # The entry point
    # ------------------------------------------------------------------

    def test_01_batch_runs_at_all(self):
        """A batch is processed end to end.

        This is the guard for the bug that made every other test here impossible:
        the method opened with `with self.env.context(sync_mode=True, ...)`, and
        `env.context` is a read-only mapping. The call raised `TypeError` before
        looking at a single record, so nothing the Master could receive was ever
        written. A green assertion on the result is what says the entry point runs.
        """
        result = self.engine.process_incoming_batch_master(
            self.SLAVE,
            [self._record('res.partner', 11, {'name': 'Remote Partner'})])

        self.assertEqual(len(result['updated_mappings']), 1)
        mapping = result['updated_mappings'][0]
        self.assertEqual(mapping['model'], 'res.partner')
        self.assertEqual(mapping['slave_id'], 11)

        partner = self.env['res.partner'].browse(mapping['master_id'])
        self.assertEqual(partner.name, 'Remote Partner')

    def test_02_sync_context_is_set(self):
        """The batch runs under the synchronization context.

        `sync_mode` is what downstream modules hang their "do not react to this
        write" behaviour on, and `tracking_disable` keeps the chatter out of a
        machine-to-machine transfer. Both were meant to be set by the call that
        raised; asserting them keeps the intent from being lost again.
        """
        captured = {}

        def spy(engine, slave_token, records):
            captured['context'] = engine.env.context
            return {'updated_mappings': []}

        self.patch(type(self.engine), '_process_incoming_batch', spy)
        self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 1, {'name': 'x'})])

        self.assertTrue(captured['context'].get('sync_mode'))
        self.assertTrue(captured['context'].get('tracking_disable'))

    def test_03_missing_token_is_refused(self):
        with self.assertRaises(ValidationError):
            self.engine.process_incoming_batch_master(
                None, [self._record('res.partner', 1, {'name': 'x'})])

    def test_04_empty_batch_is_refused(self):
        with self.assertRaises(ValidationError):
            self.engine.process_incoming_batch_master(self.SLAVE, [])

    # ------------------------------------------------------------------
    # Namespace safety
    # ------------------------------------------------------------------

    def test_05_model_without_a_rule_is_skipped(self):
        """Only what a rule names may be written.

        The Master is exposed on the network; a batch naming `res.users` or
        `ir.model.data` must not reach `create` because a Slave said so.
        """
        result = self.engine.process_incoming_batch_master(
            self.SLAVE,
            [self._record('res.currency', 7, {'name': 'ZZZ'}),
             self._record('res.partner', 8, {'name': 'Allowed'})])

        self.assertEqual([m['model'] for m in result['updated_mappings']],
                         ['res.partner'])
        self.assertFalse(self.env['res.currency'].search([('name', '=', 'ZZZ')]))

    def test_06_outgoing_only_rule_does_not_let_data_in(self):
        rule = self._rule('res.country', direction='outgoing')
        self.assertEqual(rule.direction, 'outgoing')

        result = self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.country', 3, {'name': 'Not This Way'})])

        self.assertEqual(result['updated_mappings'], [])
        self.assertFalse(self.env['res.country'].search([('name', '=', 'Not This Way')]))

    # ------------------------------------------------------------------
    # Two-phase write
    # ------------------------------------------------------------------

    def test_07_forward_reference_is_resolved_in_phase_two(self):
        """A record may point at one that comes later in the same batch.

        This is the whole reason for the two-phase write: phase one creates every
        skeleton, so by phase two both ends of the reference have a Master id.
        """
        result = self.engine.process_incoming_batch_master(self.SLAVE, [
            self._record('res.partner', 21, {
                'name': 'Child',
                'parent_id': self._ref('res.partner', 22),
            }),
            self._record('res.partner', 22, {'name': 'Parent', 'is_company': True}),
        ])

        self.assertEqual(len(result['updated_mappings']), 2)
        child = self.env['res.partner'].browse(self._master_id('res.partner', 21))
        parent = self.env['res.partner'].browse(self._master_id('res.partner', 22))
        self.assertEqual(child.parent_id, parent)

    def test_08_many2many_is_translated(self):
        result = self.engine.process_incoming_batch_master(self.SLAVE, [
            self._record('res.partner.category', 31, {'name': 'Imported Tag'}),
            self._record('res.partner', 32, {
                'name': 'Tagged',
                'category_id': [self._ref('res.partner.category', 31)],
            }),
        ])

        self.assertEqual(len(result['updated_mappings']), 2)
        partner = self.env['res.partner'].browse(self._master_id('res.partner', 32))
        self.assertEqual(partner.category_id.name, 'Imported Tag')

    def test_09_unresolvable_reference_does_not_lose_the_record(self):
        """Reference safety: an unknown target drops the field, not the record.

        A Slave may legitimately send a record whose parent it has not synchronised
        yet. Losing the whole record would mean losing it silently and for good;
        dropping the reference leaves something the next batch can complete.
        """
        result = self.engine.process_incoming_batch_master(self.SLAVE, [
            self._record('res.partner', 41, {
                'name': 'Orphan',
                'parent_id': self._ref('res.partner', 999999),
            }),
        ])

        self.assertEqual(len(result['updated_mappings']), 1)
        partner = self.env['res.partner'].browse(self._master_id('res.partner', 41))
        self.assertEqual(partner.name, 'Orphan')
        self.assertFalse(partner.parent_id)

    def test_10_one_bad_record_does_not_sink_the_batch(self):
        result = self.engine.process_incoming_batch_master(self.SLAVE, [
            self._record('res.partner', 51, {'name': 'Fine'}),
            {'model': 'res.partner', 'vals': {'name': 'No local_id'}},
            self._record('res.partner', 52, {'name': 'Also Fine'}),
        ])

        self.assertEqual(sorted(m['slave_id'] for m in result['updated_mappings']),
                         [51, 52])

    # ------------------------------------------------------------------
    # Identity and conflict
    # ------------------------------------------------------------------

    def test_11_the_same_slave_id_twice_is_one_record(self):
        """Idempotence is what makes a retry safe.

        A Slave that loses the answer sends the batch again. If the second pass
        created a second record, every dropped connection would leave a duplicate.
        """
        first = self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 61, {'name': 'Once'})])
        second = self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 61, {'name': 'Once Again'})])

        self.assertEqual(first['updated_mappings'][0]['master_id'],
                         second['updated_mappings'][0]['master_id'])
        partner = self.env['res.partner'].browse(self._master_id('res.partner', 61))
        self.assertEqual(partner.name, 'Once Again')

    def test_12_two_slaves_with_the_same_local_id_are_two_records(self):
        """Mappings are per node: local ids from different Slaves do not collide."""
        self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 71, {'name': 'From A'})])
        self.engine.process_incoming_batch_master(
            'other-slave', [self._record('res.partner', 71, {'name': 'From B'})])

        from_a = self._master_id('res.partner', 71)
        from_b = self.synch_map.get_local_id('res.partner', 71, 'other-slave')
        self.assertTrue(from_a and from_b)
        self.assertNotEqual(from_a, from_b)

    def test_13_older_incoming_change_is_ignored(self):
        """Last Write Wins, and the Master's own edit is the later one here."""
        self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 81, {'name': 'Original'})])
        partner = self.env['res.partner'].browse(self._master_id('res.partner', 81))
        partner.write({'name': 'Edited on the Master'})

        stale = fields.Datetime.to_string(partner.write_date - timedelta(hours=1))
        self.engine.process_incoming_batch_master(
            self.SLAVE,
            [self._record('res.partner', 81, {'name': 'Stale'}, write_date=stale)])

        partner.invalidate_recordset()
        self.assertEqual(partner.name, 'Edited on the Master')

    def test_14_newer_incoming_change_is_applied(self):
        self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 91, {'name': 'Original'})])
        partner = self.env['res.partner'].browse(self._master_id('res.partner', 91))

        fresh = fields.Datetime.to_string(partner.write_date + timedelta(hours=1))
        self.engine.process_incoming_batch_master(
            self.SLAVE,
            [self._record('res.partner', 91, {'name': 'Fresher'}, write_date=fresh)])

        partner.invalidate_recordset()
        self.assertEqual(partner.name, 'Fresher')

    def test_15_a_mapping_to_a_deleted_record_is_rebuilt(self):
        """The Slave still knows the old id; the Master must not answer with it."""
        self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 101, {'name': 'Doomed'})])
        first_id = self._master_id('res.partner', 101)
        self.env['res.partner'].browse(first_id).unlink()

        result = self.engine.process_incoming_batch_master(
            self.SLAVE, [self._record('res.partner', 101, {'name': 'Reborn'})])

        second_id = result['updated_mappings'][0]['master_id']
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(self.env['res.partner'].browse(second_id).name, 'Reborn')

    # ------------------------------------------------------------------
    # Field handling
    # ------------------------------------------------------------------

    def test_16_relational_fields_stay_out_of_phase_one(self):
        """Phase one must not try to write a reference it cannot resolve yet."""
        scalars = self.engine._extract_scalar_fields('res.partner', {
            'name': 'Mixed',
            'parent_id': self._ref('res.partner', 5),
            'category_id': [self._ref('res.partner.category', 6)],
        })
        self.assertEqual(set(scalars), {'name'})

    def test_17_unknown_field_names_are_dropped(self):
        """A Slave on an older schema must not be able to break `create`."""
        scalars = self.engine._extract_scalar_fields(
            'res.partner', {'name': 'Ok', 'field_that_does_not_exist': 1})
        self.assertEqual(set(scalars), {'name'})

    def test_18_compressed_binary_is_restored(self):
        payload = b'a picture, roughly' * 100
        wrapped = {
            '__type__': 'binary',
            'data': base64.b64encode(gzip.compress(payload)).decode(),
            'compressed': True,
        }
        restored = self.engine._deserialize_binary_field(wrapped)
        self.assertEqual(base64.b64decode(restored), payload)

    def test_19_malformed_binary_is_refused_not_raised(self):
        self.assertIsNone(self.engine._deserialize_binary_field(
            {'__type__': 'binary', 'data': 'not base64 at all !!', 'compressed': True}))
        self.assertIsNone(self.engine._deserialize_binary_field({'__type__': 'ref'}))
        self.assertIsNone(self.engine._deserialize_binary_field(None))
