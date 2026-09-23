# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The bj_spinner widget renders a running job in a real web client."""
from odoo.tests import HttpCase, tagged

WAIT_FOR_SPINNER = """
const deadline = Date.now() + 20000;
(function check() {
    const value = document.querySelector('.bj_spinner .o_bjprogressbar_value');
    const status = document.querySelector('.bj_spinner .o_bjprogressbar_message');
    if (value && value.textContent.includes('40 %') && status && status.textContent.includes('Step 2')) {
        console.log('test successful');
    } else if (Date.now() > deadline) {
        console.error('bj_spinner did not render the job: ' + (value ? value.textContent : 'no widget'));
    } else {
        setTimeout(check, 100);
    }
})();
"""


@tagged('post_install', '-at_install')
class TestSpinnerWidget(HttpCase):

    def test_spinner_shows_the_job(self):
        wizard = self.env['res.background_job_test'].create({'step_delay': 0})
        job = self.env['res.background_job'].create({
            'name': "Spinner smoke", 'model': wizard._name, 'res_id': wizard.id,
            'method': 'action_refresh', 'state': 'started',
            'completion_rate': 40, 'current_status': "Step 2 of 5",
        })
        wizard.write({'job': job.id, 'state': 'running'})
        action = self.env['ir.actions.act_window'].create({
            'name': "Spinner smoke", 'res_model': 'res.background_job_test',
            'view_mode': 'form', 'target': 'current',
        })
        self.browser_js('/odoo/action-%s/%s' % (action.id, wizard.id), WAIT_FOR_SPINNER,
                        "odoo.isReady === true", login='admin', timeout=120)
