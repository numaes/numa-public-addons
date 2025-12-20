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

    setType(type) {
        this.state.type = type;
        this.state.label = ''; // Reset label on type change
    }

    save() {
        let label = this.state.label;
        
        if (this.state.type === 'end') {
            label = 'End';
        } else if (this.state.type === 'transition' && !label) {
            label = 'T_' + Math.floor(Math.random() * 1000);
        } else if (this.state.type === 'state' && !label) {
            // Require label for states? Or auto-generate? Let's require it for now or default
            label = 'State_' + Math.floor(Math.random() * 1000);
        }

        this.props.onSave(this.state.type, label, this.props.x, this.props.y);
    }
}
