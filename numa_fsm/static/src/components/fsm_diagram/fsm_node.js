/** @odoo-module **/

import { Component, useState, useRef } from "@odoo/owl";

export class FSMNode extends Component {
    static template = "numa_fsm.FSMNode";
    static props = {
        node: { type: Object },
    };

    setup() {
        this.state = useState({
            isDragging: false,
        });
        this.dragStart = { x: 0, y: 0 };
    }

    onMouseDown(ev) {
        ev.stopPropagation(); // Prevent container from panning
        this.state.isDragging = true;
        this.dragStart = { x: ev.clientX, y: ev.clientY };

        const onMouseMove = (moveEv) => {
            if (this.state.isDragging) {
                const dx = moveEv.clientX - this.dragStart.x;
                const dy = moveEv.clientY - this.dragStart.y;
                
                // We need to account for the current zoom level
                const scale = this.props.node.diagramScale || 1; // This needs to be passed down
                
                this.props.node.x += dx / scale;
                this.props.node.y += dy / scale;
                
                this.dragStart = { x: moveEv.clientX, y: moveEv.clientY };
            }
        };

        const onMouseUp = () => {
            this.state.isDragging = false;
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            this.trigger("move", { nodeId: this.props.node.id, x: this.props.node.x, y: this.props.node.y });
        };

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }
}
