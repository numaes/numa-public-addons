# -*- coding: utf-8 -*-
"""The permission matrix client action in a real web client."""
from odoo.tests import HttpCase, tagged

WAIT_FOR_ROLE = """
const deadline = Date.now() + 25000;
(function check() {
    const names = [...document.querySelectorAll('.o_permission_matrix_role_name')].map((el) => el.textContent);
    if (names.some((name) => name.includes('Smoke Role'))) {
        console.log('test successful');
    } else if (Date.now() > deadline) {
        console.error('permission matrix without the role: ' + JSON.stringify(names) +
                      ' loading=' + !!document.querySelector('.o_permission_matrix_loading'));
    } else {
        setTimeout(check, 200);
    }
})();
"""


@tagged('post_install', '-at_install')
class TestPermissionMatrixWebClient(HttpCase):

    def test_matrix_lists_the_roles(self):
        self.env['res.groups'].create({'name': 'Smoke Role', 'numa_type': 'role'})
        action = self.env.ref('numa_roles.action_permission_matrix')
        self.browser_js('/odoo/action-%s' % action.id, WAIT_FOR_ROLE, "odoo.isReady === true",
                        login='admin', timeout=120)
