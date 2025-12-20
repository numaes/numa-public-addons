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
        const outcomesArray = Object.keys(this.props.node.outcomes || {}).map(key => ({
            name: key,
            target: this.props.node.outcomes[key]
        }));
        
        // Ensure __default__ exists
        if (!outcomesArray.find(o => o.name === '__default__')) {
            outcomesArray.unshift({ name: '__default__', target: null });
        }

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
        if (this.state.outcomes[index].name === '__default__') {
            alert("Cannot remove default outcome.");
            return;
        }
        this.state.outcomes.splice(index, 1);
    }

    save() {
        const outcomesObj = {};
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
