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
        // Convert outcomes object to array for easier editing
        // Filter out __default__ as it is implicit
        const outcomesArray = Object.keys(this.props.node.outcomes || {})
            .filter(key => key !== '__default__')
            .map(key => ({
                name: key,
                target: this.props.node.outcomes[key]
            }));

        this.state = useState({
            eventName: this.props.node.label || '', 
            code: this.props.node.code || '',
            outcomes: outcomesArray,
        });
    }

    onCodeChange(code) {
        this.state.code = code;
    }

    addOutcome() {
        this.state.outcomes.push({ name: 'new_outcome', target: null });
    }

    removeOutcome(index) {
        this.state.outcomes.splice(index, 1);
    }

    save() {
        // Convert array back to object
        const outcomesObj = { '__default__': null }; // Always include default
        this.state.outcomes.forEach(o => {
            if (o.name) {
                outcomesObj[o.name] = o.target;
            }
        });

        this.props.onSave({
            ...this.props.node,
            label: this.state.eventName,
            code: this.state.code,
            outcomes: outcomesObj,
        });
    }
}
