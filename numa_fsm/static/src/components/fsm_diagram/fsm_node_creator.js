/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class FSMNodeCreator extends Component {
    static template = "numa_fsm.FSMNodeCreator";
    static props = {
        onSave: Function,
        onClose: Function,
        x: Number,
        y: Number,
    };

    setup() {
        this.state = useState({
            type: 'state',
            label: '',
        });
    }

    save() {
        if (this.state.label) {
            this.props.onSave(this.state.type, this.state.label, this.props.x, this.props.y);
        }
    }
}
