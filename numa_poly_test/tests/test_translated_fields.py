"""Writing a translated field through a polymorphic model.

`numa_poly` used to carry a full copy of core's `_write_multi`, and the copy had
fallen a version behind on the one piece of SQL that is not obvious: the expression
that merges a translated jsonb column. Odoo 20 hands such a column the pair
`(is_partial, translations)` and reads `expr -> 0` and `expr -> 1` out of it, while
the copy still treated `expr` as the bare dict. What reached the column was an object
concatenated with an array, which Postgres answers with an array -- so every
translated field written through a polymorphic model was stored as
`[{...}, false, {...}]`.

Nothing noticed at write time. The next read died in `StoredTranslations(val)` with
"dictionary update sequence element #0 has length 1; 2 is required", a message that
names neither the field nor the model. Installing `website` alongside `numa_poly` hit
it inside `website`'s own post-init hook, which is why the two could not be installed
in the same run.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTranslatedFields(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Child = cls.env['test.poly.child.a']

    def _stored(self, record):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT translated_field, jsonb_typeof(translated_field) "
            "FROM %s WHERE id = %%s" % self.Child._table, (record.id,))
        return self.env.cr.fetchone()

    def test_01_a_translated_field_is_stored_as_an_object(self):
        record = self.Child.create({'child_a_field': 'A', 'translated_field': 'Hello'})

        value, kind = self._stored(record)

        self.assertEqual(kind, 'object',
                         "a translated column holds {lang: text}, never an array")
        self.assertEqual(value['en_US'], 'Hello')

    def test_02_it_reads_back(self):
        """The array was only fatal on the way out, which is what made it so quiet."""
        record = self.Child.create({'child_a_field': 'A', 'translated_field': 'Hello'})
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(record.translated_field, 'Hello')

    def test_03_a_write_after_the_create_keeps_it_an_object(self):
        """Create and write take different paths through the column expression."""
        record = self.Child.create({'child_a_field': 'A', 'translated_field': 'First'})
        self.env.flush_all()

        record.translated_field = 'Second'

        value, kind = self._stored(record)
        self.assertEqual(kind, 'object')
        self.assertEqual(value['en_US'], 'Second')

    def test_04_a_second_language_is_merged_not_replaced(self):
        """This is what the merge expression is for, and what the fork got wrong."""
        lang = self.env['res.lang']._activate_lang('fr_FR')
        if not lang:
            self.skipTest('fr_FR is not available in this database')
        # Created in English on purpose: what Odoo stores for the other languages depends
        # on the language the record is created in and on whether en_US is active.
        record = self.Child.with_context(lang='en_US').create(
            {'child_a_field': 'A', 'translated_field': 'Hello'})
        self.env.flush_all()

        record.with_context(lang='fr_FR').translated_field = 'Bonjour'

        value, kind = self._stored(record)
        self.assertEqual(kind, 'object')
        self.assertEqual(value['fr_FR'], 'Bonjour')
        if self.env['res.lang']._lang_get('en_US').active:
            self.assertEqual(value['en_US'], 'Hello')
        # Otherwise Odoo keeps en_US, the fallback, in step with the latest write: that
        # is core's rule, not poly's.

        # Exactly what Odoo stores for an ordinary translated field, either way.
        core = self.env['res.partner.category'].with_context(lang='en_US').create({'name': 'Hello'})
        self.env.flush_all()
        core.with_context(lang='fr_FR').name = 'Bonjour'
        self.env.flush_all()
        self.env.cr.execute("SELECT name FROM res_partner_category WHERE id = %s", [core.id])
        self.assertEqual(value, self.env.cr.fetchone()[0])

    def test_05_the_record_can_be_copied(self):
        """`copy_data` reads the raw translations, which is where the read blew up."""
        record = self.Child.create({'child_a_field': 'A', 'translated_field': 'Hello'})
        self.env.flush_all()

        copy = record.copy()

        self.assertEqual(copy.translated_field, 'Hello')
