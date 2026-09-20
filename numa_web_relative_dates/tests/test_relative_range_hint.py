# -*- coding: utf-8 -*-
"""The template extension is tested against the REAL bundle, not against the source file.

What can break here is not our XML -it is twelve lines- but the anchor: we inherit a
template of `web` by name, and if Odoo renames it in a later version the inheritance stops
applying. And it fails SILENTLY: `generate_xml_bundle` raises nothing when the parent of an
extension is missing, it only appends a `console.error(...)` to the bundle (assetsbundle.py,
see `missing_names_for_extension`). In production the hint would simply not appear and
nobody would find out.

It already happened once: Odoo 20 dropped the `within` operator and with it the template
`web.TreeEditor.Within` that this module inherited up to 18.0. Hence the assertions are
about the generated bundle: that the core template still exists under that name, that our
extension is registered against it, and that the text arrives.
"""

from odoo.tests import TransactionCase, tagged

CORE_TEMPLATE = 'web.TreeEditor.relativeRange'


# post_install: the bundle is assembled with EVERY installed module, so it has to be
# evaluated once the installation is finished, not in the middle of it.
@tagged('post_install', '-at_install')
class TestRelativeRangeHint(TransactionCase):

    def _bundle(self):
        """The JS that registers the backend's OWL templates."""
        bundle = self.env['ir.qweb']._get_asset_bundle(
            'web.assets_backend', css=False, js=True)
        return bundle.generate_xml_bundle()

    def test_the_core_template_still_exists(self):
        """The anchor of the inheritance. If this fails, Odoo renamed the template and it
        has to be followed -- which is exactly what happened between 18.0 and 20.0."""
        self.assertIn(
            'registerTemplate("%s"' % CORE_TEMPLATE, self._bundle(),
            'Template %s no longer exists in web. This module\'s inheritance is left '
            'dangling: find the new name of the relative range editor and update the '
            't-inherit.' % CORE_TEMPLATE)

    def test_the_extension_is_registered_against_the_template(self):
        self.assertIn(
            'registerTemplateExtension("%s"' % CORE_TEMPLATE, self._bundle(),
            'The extension did not reach the bundle: check that the XML is declared in assets.')

    def test_the_parent_is_not_missing(self):
        """The silent failure: a missing parent means a console.error in the bundle, not an
        exception."""
        bundle = self._bundle()
        faltantes = [l for l in bundle.splitlines()
                     if 'Missing (extension) parent templates' in l and CORE_TEMPLATE in l]
        self.assertEqual(
            faltantes, [],
            'The bundle reports the parent of the extension as missing: %s' % faltantes)

    def test_the_text_and_the_explanation_arrive(self):
        """What the module contributes: the visible marker and the tooltip that explains
        the recalculation."""
        bundle = self._bundle()
        self.assertIn('from today', bundle)
        self.assertIn('data-tooltip', bundle)
        self.assertIn('recalculated every time the filter runs', bundle)

    def test_the_text_is_translatable(self):
        """The msgid in the .po must be EXACTLY the text node of the template.

        With xml:space="preserve" any indentation enters the node and the translation stops
        matching. This checks that the text stays flush against its tags."""
        bundle = self._bundle()
        self.assertIn('>from today</small>', bundle,
                      'The text ended up with whitespace around it: the .po msgid will not match.')
