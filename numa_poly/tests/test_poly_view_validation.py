# -*- coding: utf-8 -*-
"""
Deferred view validation.

While modules are being loaded the polymorphic MRO can be incomplete, so poly does not validate
the views at that moment: it defers them to the end of the load. There were four chained defects:
only ``noupdate`` views were recorded, the pending set was lost on every read, the final
validation hung from a wrapper of ``load_module_graph`` that does not apply to the load in
progress (numa_poly is imported inside that call), and ``Registry.setup_models`` cleared the set
when each module started. Nothing was validated. In a real installation that left 33 broken and
active views -including syntax errors that Odoo rejects at load time- without any ``-u`` warning
about it, in modules that used poly and in modules that did not.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools import config, mute_logger

from ..models import poly as P

LOGGER = 'odoo.addons.numa_poly.models.poly'
INVALIDA = '<form><field name="x_campo_que_no_existe"/></form>'
VALIDA = '<form><field name="name"/></form>'


@tagged('post_install', '-at_install')
class TestPolyDeferredViewValidation(TransactionCase):

    def setUp(self):
        super().setUp()
        previos = set(self.registry._pending_poly_views)

        def restaurar():
            self.registry._pending_poly_views.clear()
            self.registry._pending_poly_views.update(previos)
        self.addCleanup(restaurar)

    def _crear_durante_la_carga(self, arch, nombre):
        # [poly][20.0] "during the load" used to be registry._init = True; now it is
        # registry.loaded = False (registry.py:114), with the meaning inverted.
        with patch.object(self.registry, 'loaded', False):
            return self.env['ir.ui.view'].create({
                'name': nombre, 'model': 'res.currency', 'type': 'form', 'arch': arch})

    def _finalizar(self, estricta):
        with patch.dict(config.options, {'poly_strict_view_validation': estricta}):
            self.registry._poly_finalize_view_validation(self.env.cr)

    def test_00_the_pending_set_survives_between_reads(self):
        """Every read has to return the same set. When it was a ``lazy_property`` stored under
        the name of a function different from the attribute, every read created a new one:
        everything recorded was lost and the final validation validated nothing. (That it also
        survives a ``_setup_models__`` is covered by test_poly_registry_stabilization.)"""
        pendientes = self.registry._pending_poly_views
        self.assertIs(self.registry._pending_poly_views, pendientes)

    def test_01_during_loading_an_invalid_view_is_deferred_not_forgotten(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly deferred invalid')
        self.assertIn(vista.id, self.registry._pending_poly_views,
                      "the view was not recorded: it was never going to be validated")

    def test_02_strict_finalization_rejects_it_and_names_the_cause(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly deferred invalid')
        with mute_logger(LOGGER), self.assertRaises(ValidationError) as ctx:
            self._finalizar(True)
        self.assertIn('x_campo_que_no_existe', str(ctx.exception))
        self.assertNotIn(vista.id, self.registry._pending_poly_views)

    def test_03_lenient_finalization_reports_without_aborting(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly deferred invalid')
        with self.assertLogs(LOGGER, level='ERROR') as logs:
            self._finalizar(False)
        self.assertTrue(any('x_campo_que_no_existe' in line for line in logs.output), logs.output)
        self.assertNotIn(vista.id, self.registry._pending_poly_views)

    def test_04_a_valid_deferred_view_passes_silently(self):
        vista = self._crear_durante_la_carga(VALIDA, 'poly deferred valid')
        self.assertIn(vista.id, self.registry._pending_poly_views)
        self._finalizar(True)
        self.assertNotIn(vista.id, self.registry._pending_poly_views)

    def test_05_a_view_deleted_before_the_end_is_skipped(self):
        vista = self._crear_durante_la_carga(INVALIDA, 'poly deferred deleted')
        vista.unlink()
        self._finalizar(True)

    def test_06_outside_loading_nothing_is_deferred(self):
        with self.assertRaises(ValidationError):
            self.env['ir.ui.view'].create({
                'name': 'poly immediate', 'model': 'res.currency', 'type': 'form', 'arch': INVALIDA})

    def test_08_the_registry_hook_triggers_the_final_validation(self):
        """The real trigger: Odoo calls ``_register_hook`` with every module loaded
        (``registry.py:577``). The ``load_module_graph`` wrapper is useless in a startup, because
        poly is imported inside that very call. It is the anchor that survived Odoo 20, where
        ``Registry.signal_changes`` -which the stabilization hung from- disappeared."""
        self._crear_durante_la_carga(INVALIDA, 'poly deferred from the hook')
        with patch.dict(config.options, {'poly_strict_view_validation': True}), \
                mute_logger(LOGGER), self.assertRaises(ValidationError) as ctx:
            self.env['ir.poly_base']._register_hook()
        self.assertIn('x_campo_que_no_existe', str(ctx.exception))

    def test_09_a_search_view_with_searchpanel_can_be_extended_during_loading(self):
        """Deferring a step that another one uses as a precondition is not deferring, it is
        skipping.

        ``_check_xml`` runs the RelaxNG over the tree that ``_validate_view`` has already
        normalized: ``_validate_tag_search`` takes the ``<searchpanel>`` out of the
        ``<search>`` because the RNG does not know how to validate its fields. When poly
        deferred ``_validate_view`` but let the RNG run, the panel was still there and the
        RNG rejected a valid view. With numa_poly installed no module could extend a
        search view with a searchpanel: ``hr.view_employee_filter`` has one, and that is
        why numa_fsm_hr would not install.
        """
        from odoo.tools.view_validation import relaxng
        Vista = self.env['ir.ui.view']
        base = Vista.create({
            'name': 'poly base con searchpanel', 'model': 'res.partner',
            'type': 'search', 'mode': 'primary',
            'arch': """<search>
                <field name="name"/>
                <searchpanel>
                    <field name="company_id" icon="business" icon_class="oi-filled" enable_counters="1"/>
                </searchpanel>
            </search>""",
        })
        # The why, measured and not assumed: without normalizing, the RNG rejects it.
        self.assertFalse(relaxng('search').validate(base._get_combined_arch()),
                         "if the RNG accepts the searchpanel, this test no longer proves anything")

        with patch.object(self.registry, 'loaded', False):
            extension = Vista.create({
                'name': 'poly search extension', 'model': 'res.partner',
                'inherit_id': base.id,
                'arch': '''<data><field name="name" position="after">
                             <field name="email"/>
                           </field></data>'''})
        self.assertIn(extension.id, self.registry._pending_poly_views)
        self._finalizar(True)

    def test_10_a_broken_anchor_still_fails_during_loading(self):
        """What is NOT deferred: that the inheritance resolves.

        It does not depend on the MRO, and its error names the element that was not found
        and the file where it is written. Deferring it would leave it without context.
        """
        base = self.env['ir.ui.view'].create({
            'name': 'poly base simple', 'model': 'res.partner',
            'type': 'search', 'mode': 'primary',
            'arch': '<search><field name="name"/></search>'})
        with patch.object(self.registry, 'loaded', False), \
                self.assertRaises(ValidationError) as ctx:
            self.env['ir.ui.view'].create({
                'name': 'poly ancla inexistente', 'model': 'res.partner',
                'inherit_id': base.id,
                'arch': '''<data><filter name="no_existe" position="after">
                             <field name="email"/>
                           </filter></data>'''})
        self.assertIn('no_existe', str(ctx.exception))

    def test_07_strictness_follows_the_option_then_the_test_mode(self):
        with patch.dict(config.options, {'poly_strict_view_validation': None, 'test_enable': True}):
            self.assertTrue(P._poly_strict_view_validation())
        with patch.dict(config.options, {'poly_strict_view_validation': None, 'test_enable': False}):
            self.assertFalse(P._poly_strict_view_validation())
        for valor, esperado in (('True', True), ('1', True), ('yes', True), ('false', False),
                                ('0', False), (True, True), (False, False)):
            with patch.dict(config.options, {'poly_strict_view_validation': valor, 'test_enable': False}):
                self.assertEqual(P._poly_strict_view_validation(), esperado, valor)
