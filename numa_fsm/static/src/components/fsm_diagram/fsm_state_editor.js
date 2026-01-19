/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class FSMStateEditor extends Component {
    static template = "numa_fsm.FSMStateEditor";
    static props = {
        node: Object,
        readonly: { type: Boolean, optional: true },
        onSave: Function,
        onClose: Function,
    };

    setup() {
        this.state = useState({
            label: this.props.node.label || '',
            events: [...(this.props.node.events || [])],
            is_global: this.props.node.is_global || false,
        });
    }

    addEvent() {
        this.state.events.push({ name: 'new_event' });
    }

    removeEvent(index) {
        this.state.events.splice(index, 1);
    }

    save() {
        this.props.onSave({
            ...this.props.node,
            label: this.state.label,
            events: this.state.events,
            is_global: this.state.is_global,
        });
    }
}
