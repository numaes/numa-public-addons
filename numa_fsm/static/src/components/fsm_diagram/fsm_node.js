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

        // Manual double click detection
        const now = Date.now();
        if (this.lastClickTime && (now - this.lastClickTime < 300)) {
            console.log("[FSMNode] double click detected", { nodeId: this.props.node.id });
            ev.stopPropagation();
            this.onNodeDblClick();
            this.lastClickTime = 0;
            return;
        }
        this.lastClickTime = now;
        
        // We no longer handle dragging here. 
        // We let it bubble to FSMDiagram.onMouseDown
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
