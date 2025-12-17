/** @odoo-module **/

import { Component, useState, useRef } from "@odoo/owl";

export class FSMNode extends Component {
    static template = "numa_fsm.FSMNode";
    static props = {
        node: { type: Object },
        diagramScale: { type: Number },
    };

    setup() {
        this.state = useState({
            isDragging: false,
        });
        this.dragStart = { x: 0, y: 0 };
    }

    onMouseDown(ev) {
        ev.stopPropagation();
        this.state.isDragging = true;
        this.dragStart = { x: ev.clientX, y: ev.clientY };

        const onMouseMove = (moveEv) => {
            if (this.state.isDragging) {
                const dx = moveEv.clientX - this.dragStart.x;
                const dy = moveEv.clientY - this.dragStart.y;
                
                const scale = this.props.diagramScale || 1;
                
                const newX = this.props.node.x + (dx / scale);
                const newY = this.props.node.y + (dy / scale);
                
                // Trigger move event to parent
                this.trigger("move", { nodeId: this.props.node.id, x: newX, y: newY });
                
                this.dragStart = { x: moveEv.clientX, y: moveEv.clientY };
            }
        };

        const onMouseUp = () => {
            this.state.isDragging = false;
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
        };

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }
}
