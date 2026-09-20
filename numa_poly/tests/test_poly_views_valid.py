# -*- coding: utf-8 -*-
"""
Guard: every active view in the installation validates.

poly defers view validation while modules are being loaded, and for a long time it deferred too
much: the views that were not ``noupdate`` were never validated. This test validates every active
view with the full registry, the same way Odoo would when loading them, and lists each failure
with its cause. It also walks those of modules that do not use poly, because the omission
reached all of them.

If it fails in an installation, what is broken is the view it names, not poly.
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
            except Exception as e:  # noqa: BLE001 - all of them are listed, not just the first
                texto = str(e).strip()
                causa = texto.splitlines()[-1] if texto else repr(e)
                xmlid = vista.get_external_id().get(vista.id) or 'id %s' % vista.id
                fallas[(vista.model, causa)].append(xmlid)
        self.assertFalse(
            fallas,
            "%d active view(s) do not validate:\n%s" % (
                sum(len(v) for v in fallas.values()),
                '\n'.join('  [%s] %s\n      %s' % (modelo, causa, ', '.join(xs))
                          for (modelo, causa), xs in sorted(fallas.items()))))
