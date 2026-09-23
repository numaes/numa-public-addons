# -*- coding: utf-8 -*-
"""The FSM designer in a real web client.

The Python suite exercises the engine; only a browser shows whether the
fsm_diagram widget still renders. It did not after the move to OWL 3.
"""
from odoo.tests import HttpCase, tagged

from .test_fsm_live import _schema

WAIT_FOR_DIAGRAM = """
const expected = %d;
const deadline = Date.now() + 20000;
(function check() {
    const nodes = document.querySelectorAll('.o_field_fsm_diagram .o_fsm_node');
    const paths = [...document.querySelectorAll('.o_field_fsm_diagram path.o_fsm_connection')];
    const drawn = paths.filter((p) => (p.getAttribute('d') || '').length && !/NaN|undefined/.test(p.getAttribute('d')));
    if (nodes.length === expected && drawn.length === %d) {
        console.log('test successful');
    } else if (Date.now() > deadline) {
        console.error('fsm_diagram drew ' + nodes.length + ' node(s) and ' + drawn.length +
                      ' connection(s) of ' + paths.length);
    } else {
        setTimeout(check, 100);
    }
})();
"""


@tagged('post_install', '-at_install')
class TestFsmWebClient(HttpCase):

    def test_web_client_boots(self):
        self.browser_js('/odoo', "console.log('test successful')", "odoo.isReady === true",
                        login='admin', timeout=120)

    def test_designer_draws_every_node_and_connection(self):
        schema = _schema()
        # Placed as the designer saves them: one column per step of the workflow.
        for index, node in enumerate(schema['nodes']):
            node.update(x=60 + 220 * (index // 3), y=40 + 140 * (index % 3))
        definition = self.env['fsm.definition'].create({'name': 'Designer smoke', 'json_ui_schema': schema})
        action = self.env.ref('numa_fsm.definition_action')
        self.browser_js('/odoo/action-%s/%s' % (action.id, definition.id),
                        WAIT_FOR_DIAGRAM % (len(schema['nodes']), len(schema['connections'])),
                        "odoo.isReady === true", login='admin', timeout=120)
