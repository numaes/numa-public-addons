/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { CodeEditor } from "@web/core/code_editor/code_editor";

export class FSMTransitionEditor extends Component {
    static template = "numa_fsm.FSMTransitionEditor";
    static components = { CodeEditor };
    static props = {
        node: Object,
        onSave: Function,
        onClose: Function,
    };

    setup() {
        this.state = useState({
            eventName: this.props.node.eventName || '',
            code: this.props.node.code || '',
            outcomes: this.props.node.outcomes || {},
        });
    }

    onCodeChange(code) {
        this.state.code = code;
    }

    save() {
        this.props.onSave({
            ...this.props.node,
            eventName: this.state.eventName,
            code: this.state.code,
            outcomes: this.state.outcomes,
        });
    }
}
