# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The web client must start with this module installed.

A JS module that fails to load (an OWL 2 API that OWL 3 no longer has, say) takes
every other module down with it: the page shows "modules could not be loaded" and
nothing works. The Python suite cannot see that; only a browser can.
"""
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestWebClientBoots(HttpCase):

    def test_web_client_boots(self):
        self.browser_js('/odoo', "console.log('test successful')", "odoo.isReady === true",
                        login='admin', timeout=120)
