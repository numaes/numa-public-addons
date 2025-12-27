/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched } from "@odoo/owl";

export class FSMNode extends Component {
    static template = "numa_fsm.FSMNode";
    static props = {
        node: { type: Object },
        diagramScale: { type: Number },
        selected: { type: Boolean, optional: true },
        onMove: { type: Function },
        onResize: { type: Function },
        onPortMouseDown: { type: Function },
        onNodeDblClick: { type: Function },
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
        
        if (ev.button !== 0) {
            return;
        }
        ev.stopPropagation();
        
        // Notify parent about the click for selection
        this.env.bus.trigger('fsm_node_click', { event: ev, nodeId: this.props.node.id });

        this.state.isDragging = true;
        this.dragStart = { x: ev.clientX, y: ev.clientY };

        const onMouseMove = (moveEv) => {
            if (this.state.isDragging) {
                const dx = moveEv.clientX - this.dragStart.x;
                const dy = moveEv.clientY - this.dragStart.y;
                
                const scale = this.props.diagramScale || 1;
                
                if (this.props.onMove) {
                    this.props.onMove({ nodeId: this.props.node.id, dx: dx / scale, dy: dy / scale });
                } else {
                }
                
                this.dragStart = { x: moveEv.clientX, y: moveEv.clientY };
            }
        };

        const onMouseUp = () => {
            this.state.isDragging = false;
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            if (this.props.onMove) {
                // Signal move end to save data
                this.props.onMove({ nodeId: this.props.node.id, dx: 0, dy: 0, end: true });
            }
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

    onNodeDblClick() {
        if (this.props.onNodeDblClick) {
            this.props.onNodeDblClick(this.props.node.id);
        } else {
        }
    }
}
