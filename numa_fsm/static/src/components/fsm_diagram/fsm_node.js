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

        onMounted(() => {
            this.checkSize();
        });
        onPatched(() => {
            this.checkSize();
        });
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
        console.log("[FSMNode] onNodeMouseDown called", { nodeId: this.props.node.id, button: ev.button });
        if (ev.button !== 0) {
            return;
        }
        
        // Notify parent about the click for selection
        console.log("[FSMNode] triggering fsm_node_click on bus");
        this.env.bus.trigger('fsm_node_click', { event: ev, nodeId: this.props.node.id });

        this.state.isDragging = true;
        this.dragStart = { x: ev.clientX, y: ev.clientY };
        console.log("[FSMNode] drag started at", this.dragStart);

        const onMouseMove = (moveEv) => {
            if (this.state.isDragging) {
                const dx = moveEv.clientX - this.dragStart.x;
                const dy = moveEv.clientY - this.dragStart.y;
                
                const scale = this.props.diagramScale || 1;
                
                if (Math.abs(dx) > 0 || Math.abs(dy) > 0) {
                    if (this.props.onMove) {
                        this.props.onMove({ nodeId: this.props.node.id, dx: dx / scale, dy: dy / scale });
                    }
                    this.dragStart = { x: moveEv.clientX, y: moveEv.clientY };
                }
            }
        };

        const onMouseUp = (upEv) => {
            console.log("[FSMNode] onMouseUp - ending drag");
            this.state.isDragging = false;
            window.removeEventListener("mousemove", onMouseMove, true);
            window.removeEventListener("mouseup", onMouseUp, true);
            if (this.props.onMove) {
                // Signal move end to save data
                console.log("[FSMNode] calling onMove with end:true");
                this.props.onMove({ nodeId: this.props.node.id, dx: 0, dy: 0, end: true });
            }
        };

        window.addEventListener("mousemove", onMouseMove, true);
        window.addEventListener("mouseup", onMouseUp, true);
    }

    onPortMouseDown(ev, portName) {
        console.log("[FSMNode] onPortMouseDown", { portName, nodeId: this.props.node.id });
        ev.stopPropagation();
        if (this.props.onPortMouseDown) {
            this.props.onPortMouseDown({ event: ev, portName: portName, nodeId: this.props.node.id });
        }
    }

    onNodeDblClick() {
        console.log("[FSMNode] onNodeDblClick start", { nodeId: this.props.node.id });
        if (this.props.onNodeDblClick) {
            console.log("[FSMNode] calling props.onNodeDblClick");
            this.props.onNodeDblClick(this.props.node.id);
        } else {
            console.warn("[FSMNode] props.onNodeDblClick is missing");
        }
    }
}
