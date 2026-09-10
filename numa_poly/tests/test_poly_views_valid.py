# -*- coding: utf-8 -*-
"""
Guardia: toda vista activa de la instalación valida.

poly difiere la validación de vistas mientras se cargan módulos, y durante mucho tiempo la
difirió de más: las vistas que no eran ``noupdate`` no se validaban nunca. Este test valida todas
las vistas activas con el registry completo, igual que lo haría Odoo al cargarlas, y lista cada
falla con su causa. Recorre también las de módulos que no usan poly, porque la omisión los
alcanzaba a todos.

Si falla en una instalación, lo que está roto es la vista que nombra, no poly.
"""
from collections import defaultdict

from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestPolyAllViewsValidate(TransactionCase):

    def test_every_active_view_validates(self):
        fallas = defaultdict(list)
        for vista in self.env['ir.ui.view'].search([]):
            try:
                with self.env.cr.savepoint():
                    vista._check_xml()
            except Exception as e:  # noqa: BLE001 — se listan todas, no solo la primera
                texto = str(e).strip()
                causa = texto.splitlines()[-1] if texto else repr(e)
                xmlid = vista.get_external_id().get(vista.id) or 'id %s' % vista.id
                fallas[(vista.model, causa)].append(xmlid)
        self.assertFalse(
            fallas,
            "%d vista(s) activa(s) no validan:\n%s" % (
                sum(len(v) for v in fallas.values()),
                '\n'.join('  [%s] %s\n      %s' % (modelo, causa, ', '.join(xs))
                          for (modelo, causa), xs in sorted(fallas.items()))))
