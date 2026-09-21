"""The shared engine: serialisation, references, and the schema handshake."""

import base64
import gzip

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestSynchEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env['numa.synch.engine']
        cls.Map = cls.env['numa.synch.map']
        cls.rule = cls.env['numa.synch.rule'].create({
            'name': 'Partners',
            'model_id': cls.env['ir.model']._get_id('res.partner'),
        })

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def test_01_scalars_travel_as_themselves(self):
        partner = self.env['res.partner'].create(
            {'name': 'Serialised', 'ref': 'SER-1',
             'website': 'https://example.com', 'active': True})

        vals, _deps = self.engine._serialize_record(partner)

        self.assertEqual(vals['name'], 'Serialised')
        self.assertEqual(vals['ref'], 'SER-1')
        self.assertEqual(vals['website'], 'https://example.com')
        self.assertIs(vals['active'], True)

    def test_02_a_many2one_travels_as_a_reference(self):
        """Ids are local to a node, so a raw id would mean nothing on arrival."""
        parent = self.env['res.partner'].create({'name': 'Parent', 'is_company': True})
        child = self.env['res.partner'].create({'name': 'Child', 'parent_id': parent.id})

        vals, dependencies = self.engine._serialize_record(child)

        self.assertEqual(vals['parent_id'],
                         {'__type__': 'ref', 'model': 'res.partner', 'id': parent.id})
        self.assertIn(parent, dependencies)

    def test_03_system_fields_are_left_behind(self):
        partner = self.env['res.partner'].create({'name': 'Plain'})

        vals, _deps = self.engine._serialize_record(partner)

        for field_name in ('id', 'create_uid', 'create_date',
                           'write_uid', 'write_date', 'display_name'):
            self.assertNotIn(field_name, vals)

    def test_04_related_fields_are_left_behind(self):
        """They are a view of another field; sending them would fight the source."""
        partner = self.env['res.partner'].create({'name': 'Plain'})

        vals, _deps = self.engine._serialize_record(partner)

        related = [name for name, field in partner._fields.items() if field.related]
        self.assertTrue(related, 'res.partner should have related fields to check.')
        for field_name in related:
            self.assertNotIn(field_name, vals)

    def test_05_a_recordset_of_many_is_refused(self):
        partners = self.env['res.partner'].create(
            [{'name': 'One'}, {'name': 'Two'}])

        with self.assertRaises(ValidationError):
            self.engine._serialize_record(partners)

    def test_06_binary_fields_stay_home_unless_the_rule_says_otherwise(self):
        """They are the expensive part of a payload, so they are opt-in."""
        partner = self.env['res.partner'].create({'name': 'With Image'})

        vals, _deps = self.engine._serialize_record(partner, sync_rule=self.rule)

        self.assertFalse(self.rule.sync_binary_fields)
        self.assertNotIn('image_1920', vals)

    def test_07_a_binary_field_makes_the_round_trip(self):
        payload = b'not really a png, but long enough to compress' * 50
        wrapped = self.engine._serialize_binary_field(
            base64.b64encode(payload).decode(), max_size_mb=10.0, compress=True)

        self.assertEqual(wrapped['__type__'], 'binary')
        self.assertTrue(wrapped['compressed'])
        restored = self.engine._deserialize_binary_field(wrapped)
        self.assertEqual(base64.b64decode(restored), payload)

    def test_08_a_binary_field_over_the_limit_is_dropped(self):
        payload = base64.b64encode(b'x' * (2 * 1024 * 1024)).decode()

        self.assertFalse(self.engine._serialize_binary_field(
            payload, max_size_mb=0.001, compress=False))

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    def test_09_a_reference_resolves_through_the_mapping(self):
        self.Map.set_mapping('res.partner', 42, 900, 'NODE-A')

        resolved = self.engine._parse_incoming_ref(
            {'__type__': 'ref', 'model': 'res.partner', 'id': 900}, 'NODE-A')

        self.assertEqual(resolved, 42)

    def test_10_an_unmapped_reference_is_false(self):
        self.assertFalse(self.engine._parse_incoming_ref(
            {'__type__': 'ref', 'model': 'res.partner', 'id': 999999}, 'NODE-A'))

    def test_11_a_malformed_reference_is_false_not_an_error(self):
        for bad in (None, 'not a dict', {}, {'__type__': 'binary'},
                    {'__type__': 'ref', 'model': 'res.partner'}):
            self.assertFalse(self.engine._parse_incoming_ref(bad, 'NODE-A'))

    # ------------------------------------------------------------------
    # The handshake
    # ------------------------------------------------------------------

    def test_12_system_metadata_can_be_built_at_all(self):
        """It reads the database UUID, and the call that read it no longer existed.

        `ir.config_parameter.get_param` was removed in 20.0 in favour of the typed
        accessors, so this raised `AttributeError` -- and since the metadata is built
        at the start of every cycle, no batch could leave the Slave.
        """
        meta = self.engine._get_system_metadata()

        self.assertTrue(meta['odoo_version'])
        self.assertTrue(meta['db_uuid'])
        self.assertTrue(meta['module_version'])

    def test_13_a_model_hash_is_stable(self):
        first = self.engine._compute_model_hash('res.partner')
        second = self.engine._compute_model_hash('res.partner')

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_14_different_models_hash_differently(self):
        self.assertNotEqual(self.engine._compute_model_hash('res.partner'),
                            self.engine._compute_model_hash('res.country'))

    @mute_logger('odoo.addons.numa_synch.models.numa_synch_engine')
    def test_15_an_unknown_model_has_no_hash(self):
        self.assertIsNone(self.engine._compute_model_hash('no.such.model'))

    def test_16_matching_metadata_passes(self):
        meta = {
            'system': self.engine._get_system_metadata(),
            'models': {'res.partner': self.engine._compute_model_hash(
                'res.partner', self.rule)},
        }

        self.engine._validate_metadata(meta, ['res.partner'])

    def test_17_a_different_odoo_version_is_refused(self):
        """Two versions of the same model are not the same model."""
        meta = {'system': dict(self.engine._get_system_metadata(),
                               odoo_version='18.0'),
                'models': {}}

        with self.assertRaises(UserError) as caught:
            self.engine._validate_metadata(meta, ['res.partner'])

        self.assertIn('Version Mismatch', str(caught.exception))

    def test_18_a_different_schema_is_refused(self):
        """A field that exists on one side and not the other silently loses data.

        The wording is not pinned, only the refusal and the model it names:
        `numa_synch_ai_assisted` catches this one to try to map the two schemas onto
        each other, and rewords it when it cannot. What must not change is that a
        batch built against a different schema does not get written.
        """
        meta = {'system': self.engine._get_system_metadata(),
                'models': {'res.partner': '0' * 64}}

        with self.assertRaises(UserError) as caught:
            self.engine._validate_metadata(meta, ['res.partner'])

        self.assertIn('res.partner', str(caught.exception))

    def test_19_missing_metadata_is_refused(self):
        with self.assertRaises(UserError):
            self.engine._validate_metadata({}, ['res.partner'])

    @mute_logger('odoo.addons.numa_synch.models.numa_synch_engine')
    def test_20_a_different_database_is_only_noted(self):
        """Different databases is the normal case -- that is the whole point."""
        meta = {'system': dict(self.engine._get_system_metadata(),
                               db_uuid='some-other-database'),
                'models': {'res.partner': self.engine._compute_model_hash(
                    'res.partner', self.rule)}}

        self.engine._validate_metadata(meta, ['res.partner'])
