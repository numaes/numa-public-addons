"""Shared setup for the Master's tests."""

from odoo.tests import TransactionCase


class MasterSynchCase(TransactionCase):
    """A Master with rules for two related models and a known Slave token."""

    SLAVE = 'slave-token-for-tests'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env['numa.synch.engine']
        cls.synch_map = cls.env['numa.synch.map']

        # `res.partner` and `res.partner.category` are enough to exercise every
        # branch: scalars, a many2one between them, and a many2many back.
        cls.rule_partner = cls._rule('res.partner')
        cls.rule_category = cls._rule('res.partner.category')

    @classmethod
    def _rule(cls, model_name, **overrides):
        model_id = cls.env['ir.model']._get_id(model_name)
        assert model_id, '%s is not a model in this database.' % model_name
        vals = {
            'name': 'Sync %s' % model_name,
            'model_id': model_id,
            'direction': 'bidirectional',
        }
        vals.update(overrides)
        return cls.env['numa.synch.rule'].create(vals)

    def _record(self, model, local_id, vals, write_date=None):
        """One entry of a batch, as the Slave serialises it."""
        entry = {'model': model, 'local_id': local_id, 'vals': vals}
        if write_date:
            entry['write_date'] = write_date
        return entry

    def _ref(self, model, local_id):
        """A reference as the Slave's serialiser emits it."""
        return {'__type__': 'ref', 'model': model, 'id': local_id}

    def _master_id(self, model, slave_id):
        return self.synch_map.get_local_id(model, slave_id, self.SLAVE)
