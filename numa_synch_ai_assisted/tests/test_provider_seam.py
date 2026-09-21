# -*- coding: utf-8 -*-
"""Who answers the AI question, and what happens when nobody does.

This module used to depend on `numa_ai`, so a database without it could not install it
at all -- not even to use a transformation map somebody had written by hand. The
dependency is a seam now: `_ask_llm` is declared here and implemented by a bridge,
`numa_synch_ai_assisted_numa_ai`, which installs itself when both sides are present.

What these tests hold down is the part that is easy to lose: that the seam says
something useful when there is no provider, and that nothing in this module names one.
"""
import ast
import pathlib

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

RAIZ = pathlib.Path(__file__).resolve().parent.parent


@tagged('post_install', '-at_install')
class TestProviderSeam(TransactionCase):

    def test_01_the_module_does_not_depend_on_a_provider(self):
        manifest = ast.literal_eval((RAIZ / '__manifest__.py').read_text())
        self.assertNotIn('numa_ai', manifest['depends'],
                         "the provider is wired in by a bridge, not required here")

    def test_02_no_provider_is_used_in_the_code(self):
        """Naming the provider is how the seam is explained; reaching for it is the
        thing that must not happen here. So this looks for use -- a model lookup or an
        import -- and not for the word."""
        USOS = ("env['numa.ai", 'env["numa.ai', 'from odoo.addons.numa_ai',
                'import numa_ai')
        culpables = []
        for archivo in RAIZ.rglob('*.py'):
            if 'tests' in archivo.parts or '__pycache__' in archivo.parts:
                continue
            for n, linea in enumerate(archivo.read_text().splitlines(), 1):
                if any(uso in linea for uso in USOS):
                    culpables.append('%s:%s %s' % (archivo.name, n, linea.strip()))
        self.assertFalse(culpables, "a provider is reached for outside the bridge:\n%s"
                         % '\n'.join(culpables))

    def test_03_without_a_provider_the_seam_says_so(self):
        """And says it as a UserError, not as a KeyError on a model that is not in the
        registry, which is what asking `env['numa.ai.engine']` would have done."""
        if 'numa.ai.engine' in self.env:
            self.skipTest("a provider is installed, so the seam is implemented")
        with self.assertRaises(UserError) as ctx:
            self.env['numa.synch.engine']._ask_llm('anything')
        mensaje = str(ctx.exception)
        self.assertIn('No AI provider', mensaje)
        self.assertIn('numa_synch_ai_assisted_numa_ai', mensaje,
                      "the message must name the bridge that fixes it")

    def test_04_the_bridge_declares_both_sides_and_installs_itself(self):
        puente = RAIZ.parent / 'numa_synch_ai_assisted_numa_ai' / '__manifest__.py'
        self.assertTrue(puente.exists(), "the bridge module is missing")
        manifest = ast.literal_eval(puente.read_text())
        self.assertEqual(sorted(manifest['depends']),
                         ['numa_ai', 'numa_synch_ai_assisted'])
        self.assertTrue(manifest['auto_install'],
                        "the bridge is pointless if somebody has to install it by hand")

    def test_05_the_cache_works_without_any_provider(self):
        """What the module still does on its own: a map written by hand is used."""
        mapa = self.env['numa.synch.ai.map'].create({
            'remote_token': 'node-a',
            'model_name': 'res.partner',
            'mapping_json': '{"nombre": "name"}',
            'confidence_score': 1.0,
        })
        encontrado = self.env['numa.synch.engine']._get_cached_mapping('node-a', 'res.partner')
        self.assertEqual(encontrado, mapa)


@tagged('post_install', '-at_install')
class TestWhatIsIntercepted(TransactionCase):
    """Which refusals this module takes over, and which it must let through.

    It used to catch `UserError`, which is every refusal the base engine makes. An
    Odoo version that does not match and metadata that is missing altogether were
    handed to the AI as well -- and neither is something a field map can repair, so
    the operator got "AI analysis failed" where the real answer was "these two
    databases are on different versions of Odoo".
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env['numa.synch.engine']
        cls.rule = cls.env['numa.synch.rule'].create({
            'name': 'Partners',
            'model_id': cls.env['ir.model']._get_id('res.partner'),
        })

    def _meta(self, **system_overrides):
        system = dict(self.engine._get_system_metadata(), **system_overrides)
        return {'system': system, 'models': {}}

    def test_06_a_version_mismatch_travels_out_untouched(self):
        with self.assertRaises(UserError) as caught:
            self.engine._validate_metadata(self._meta(odoo_version='18.0'),
                                           ['res.partner'])

        self.assertIn('Version Mismatch', str(caught.exception),
                      "the operator has to read why, and an AI cannot fix a version")

    def test_07_absent_metadata_travels_out_untouched(self):
        with self.assertRaises(UserError) as caught:
            self.engine._validate_metadata({}, ['res.partner'])

        self.assertIn('Metadata is required', str(caught.exception))

    def test_08_a_low_confidence_answer_keeps_its_own_report(self):
        """An AI that says "I am not sure" is an answer, not a failure.

        The refusal it produces points at the gap-analysis report, which is the one
        thing that tells the operator where the two schemas diverge. It used to be
        raised inside the `try` that wraps the AI call, so the generic handler caught
        it and reworded it as "AI analysis failed" -- the message said the opposite of
        what had happened, and the report went unmentioned.
        """
        self.patch(type(self.engine), '_analyze_schema_with_ai',
                   lambda self, model_name, meta, token: {
                       'confidence_score': 0.4,
                       'mapping': {},
                       'critical_issues': ['two fields could be `name`'],
                   })
        meta = {'system': self.engine._get_system_metadata(),
                'models': {'res.partner': '0' * 64}}

        with self.assertRaises(UserError) as caught:
            self.engine._validate_metadata(meta, ['res.partner'])

        message = str(caught.exception)
        self.assertIn('Gap Analysis', message)
        self.assertNotIn('AI analysis failed', message)

    def test_10_a_provider_that_breaks_is_reported_as_a_failure(self):
        """And the other side of the same split: a provider that raises is a failure,
        and must not be dressed up as a considered opinion about the schema."""
        def explode(self, model_name, meta, token):
            raise RuntimeError('the provider is down')

        self.patch(type(self.engine), '_analyze_schema_with_ai', explode)
        meta = {'system': self.engine._get_system_metadata(),
                'models': {'res.partner': '0' * 64}}

        with self.assertRaises(UserError) as caught:
            self.engine._validate_metadata(meta, ['res.partner'])

        self.assertIn('AI analysis failed', str(caught.exception))

    def test_09_matching_metadata_still_passes(self):
        meta = {
            'system': self.engine._get_system_metadata(),
            'models': {'res.partner': self.engine._compute_model_hash(
                'res.partner', self.rule)},
        }

        self.engine._validate_metadata(meta, ['res.partner'])
