# -*- coding: utf-8 -*-
"""La extensión de plantilla se prueba contra el bundle REAL, no contra el archivo fuente.

Lo que puede romperse acá no es nuestro XML —son doce líneas—, es el ancla: heredamos una
plantilla de `web` por nombre, y si Odoo la renombra en una versión siguiente la herencia deja de
aplicarse. Y falla EN SILENCIO: `generate_xml_bundle` no levanta excepción cuando falta el padre
de una extensión, sólo agrega un `console.error(...)` al bundle (assetsbundle.py, ver
`missing_names_for_extension`). O sea que en producción el cartel simplemente no aparecería y
nadie se enteraría.

Por eso las aserciones son sobre el bundle generado: que la plantilla de core siga existiendo con
ese nombre, que nuestra extensión quede registrada contra ella, y que el texto llegue.
"""

from odoo.tests import TransactionCase, tagged

CORE_TEMPLATE = 'web.TreeEditor.Within'


# post_install: el bundle se arma con TODOS los módulos instalados, así que tiene que evaluarse
# una vez terminada la instalación, no en medio.
@tagged('post_install', '-at_install')
class TestWithinHint(TransactionCase):

    def _bundle(self):
        """El JS que registra las plantillas OWL del backend."""
        bundle = self.env['ir.qweb']._get_asset_bundle(
            'web.assets_backend', css=False, js=True)
        return bundle.generate_xml_bundle()

    def test_plantilla_de_core_sigue_existiendo(self):
        """El ancla de la herencia. Si esto falla, Odoo renombró la plantilla y hay que seguirla."""
        self.assertIn(
            'registerTemplate("%s"' % CORE_TEMPLATE, self._bundle(),
            'La plantilla %s ya no existe en web. La herencia de este módulo quedó colgada: hay '
            'que buscar el nuevo nombre del editor del operador `within` y actualizar el '
            't-inherit.' % CORE_TEMPLATE)

    def test_extension_registrada_contra_la_plantilla(self):
        self.assertIn(
            'registerTemplateExtension("%s"' % CORE_TEMPLATE, self._bundle(),
            'La extensión no llegó al bundle: revisá que el XML esté declarado en assets.')

    def test_el_padre_no_falta(self):
        """La falla silenciosa: padre ausente => console.error en el bundle, sin excepción."""
        bundle = self._bundle()
        faltantes = [l for l in bundle.splitlines()
                     if 'Missing (extension) parent templates' in l and CORE_TEMPLATE in l]
        self.assertEqual(
            faltantes, [],
            'El bundle denuncia que falta el padre de la extensión: %s' % faltantes)

    def test_el_texto_y_la_explicacion_llegan(self):
        """El aporte del módulo: el marcador visible y el tooltip que explica el recálculo."""
        bundle = self._bundle()
        self.assertIn('from today', bundle)
        self.assertIn('data-tooltip', bundle)
        self.assertIn('recalculated every time the filter runs', bundle)

    def test_el_texto_es_traducible(self):
        """El msgid del .po tiene que ser EXACTAMENTE el nodo de texto de la plantilla.

        Con xml:space="preserve" cualquier indentación entra en el nodo y la traducción no
        engancha. Se verifica que el texto quede pegado a sus etiquetas."""
        bundle = self._bundle()
        self.assertIn('>from today</small>', bundle,
                      'El texto quedó con espacios alrededor: el msgid del .po no va a coincidir.')
