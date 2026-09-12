# -*- coding: utf-8 -*-
"""A module is translated, or it is half translated, which is worse.

A module whose error messages are in Spanish and whose field labels are in
English is not in Spanish: it *looks* translated, which is how it stays that
way. This check reads every translatable term a module exposes — the same way
``--i18n-export`` reads them — and requires each one to carry a non-empty
translation in its ``.po``.

It lives here because ``numa_physical_product`` is the lowest module the whole
configurator family depends on, so every one of them can import it:

    from odoo.addons.numa_physical_product.tests.translation_check import (
        TranslationCoverage)

    class TestSpanish(TranslationCoverage, TransactionCase):
        TRANSLATED_MODULE = 'numa_cut_planning'
"""

import re

QUOTED = r'(?:"(?:[^"\\]|\\.)*"\s*)+'


def _unquote(raw):
    joined = ''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', raw))
    return (joined.replace('\\n', '\n').replace('\\t', '\t')
            .replace('\\"', '"').replace('\\\\', '\\'))


def parse_po(path):
    """A ``.po`` file as ``{source: translation}``.

    Read from the file rather than from the database, so the check holds on a
    database where Spanish is not installed.
    """
    with open(path, encoding='utf-8') as handle:
        text = handle.read()
    entries = {}
    for block in text.split('\n\n'):
        match = re.search(r'^msgid (%s)msgstr (%s)' % (QUOTED, QUOTED),
                          block, re.M)
        if match:
            entries[_unquote(match.group(1))] = _unquote(match.group(2))
    entries.pop('', None)
    return entries


class TranslationCoverage(object):
    """Mixin: every term of ``TRANSLATED_MODULE`` is translated into Spanish."""

    #: The module whose terms are checked. Set it in the subclass.
    TRANSLATED_MODULE = None
    #: The language file that has to cover them.
    TRANSLATED_LANG = 'es'

    def _po_path(self):
        from odoo.tools.misc import file_path
        return file_path('%s/i18n/%s.po'
                         % (self.TRANSLATED_MODULE, self.TRANSLATED_LANG))

    def _po_entries(self):
        return parse_po(self._po_path())

    def _terms_in_the_module(self, python_only=False):
        """Every translatable term the module exposes."""
        from odoo.tools.translate import TranslationModuleReader
        reader = TranslationModuleReader(
            self.env.cr, modules=[self.TRANSLATED_MODULE])
        return {source
                for _module, _ttype, _name, _res_id, source, _value, comments
                in reader
                if source and
                (not python_only or 'odoo-python' in (comments or ()))}

    def test_the_translation_file_is_actually_read(self):
        """Odoo 18 only reads a Python entry that carries `#. odoo-python`.

        A hand-written file without it parses to zero entries while looking
        perfectly correct. That happened once and cost an afternoon.
        """
        from odoo.tools.translate import code_translations
        self.assertTrue(
            code_translations.get_python_translations(
                self.TRANSLATED_MODULE, self.TRANSLATED_LANG),
            "%s parsed to nothing" % self._po_path())

    def test_every_message_the_user_can_hit_is_translated(self):
        from odoo.tools.translate import code_translations
        translations = code_translations.get_python_translations(
            self.TRANSLATED_MODULE, self.TRANSLATED_LANG)
        missing = sorted(msgid for msgid in self._terms_in_the_module(True)
                         if not translations.get(msgid, '').strip())
        self.assertFalse(
            missing,
            "%d mensajes sin traducir:\n  - %s"
            % (len(missing), '\n  - '.join(m[:90] for m in missing)))

    def test_every_label_the_user_can_see_is_translated(self):
        entries = self._po_entries()
        missing = sorted(term for term in self._terms_in_the_module()
                         if not entries.get(term, '').strip())
        self.assertFalse(
            missing,
            "%d terminos sin traducir:\n  - %s"
            % (len(missing), '\n  - '.join(t[:90] for t in missing)))

    def test_the_translation_file_has_nothing_left_over(self):
        """Una entrada sin termino detras es una traduccion que nadie ve."""
        in_module = self._terms_in_the_module()
        stale = sorted(term for term in self._po_entries()
                       if term not in in_module)
        self.assertFalse(
            stale,
            "%d entradas que ya no existen en el modulo:\n  - %s"
            % (len(stale), '\n  - '.join(t[:90] for t in stale)))

    def test_the_spanish_keeps_every_placeholder(self):
        """A dropped placeholder is a KeyError in front of a user."""
        for msgid, msgstr in self._po_entries().items():
            if not msgstr.strip():
                continue
            self.assertEqual(
                sorted(re.findall(r'%\((\w+)\)', msgid)),
                sorted(re.findall(r'%\((\w+)\)', msgstr)),
                "placeholders differ in: %s" % msgid)
