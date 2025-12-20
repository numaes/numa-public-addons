/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched } from "@odoo/owl";

export class FSMNode extends Component {
    static template = "numa_fsm.FSMNode";
    static props = {
        node: { type: Object },
        diagramScale: { type: Number },
        onMove: { type: Function },
        onResize: { type: Function },
        onPortMouseDown: { type: Function },
    };

    setup() {
        this.nodeRef = useRef("node");
        this.state = useState({
            isDragging: false,
        });
        this.dragStart = { x: 0, y: 0 };
        this.lastHeight = 0;

        onMounted(this.checkSize.bind(this));
        onPatched(this.checkSize.bind(this));
    }

    checkSize() {
        if (this.nodeRef.el) {
            const height = this.nodeRef.el.offsetHeight;
            if (height !== this.lastHeight) {
                this.lastHeight = height;
                if (this.props.onResize) {
                    this.props.onResize({ nodeId: this.props.node.id, height });
                }
            }
        }
    }

    onNodeMouseDown(ev) {
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
                
                if (this.props.onMove) {
                    this.props.onMove({ nodeId: this.props.node.id, x: newX, y: newY });
                }
                
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

    onPortMouseDown(ev, portName) {
        ev.stopPropagation();
        if (this.props.onPortMouseDown) {
            this.props.onPortMouseDown({ event: ev, portName: portName, nodeId: this.props.node.id });
        }
    }
}
