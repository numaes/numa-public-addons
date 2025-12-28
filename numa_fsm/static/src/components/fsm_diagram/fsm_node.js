/** @odoo-module **/

import { Component, useRef, onMounted, onPatched } from "@odoo/owl";

export class FSMNode extends Component {
    static template = "numa_fsm.FSMNode";
    static props = {
        node: { type: Object },
        diagramScale: { type: Number },
        selected: { type: Boolean, optional: true },
        hovered: { type: Boolean, optional: true },
        isConnecting: { type: Boolean, optional: true },
        onMove: { type: Function, optional: true },
        onResize: { type: Function, optional: true },
        onPortMouseDown: { type: Function, optional: true },
        onNodeDblClick: { type: Function, optional: true },
        onPointerEnter: { type: Function, optional: true },
        onPointerLeave: { type: Function, optional: true },
    };

    setup() {
        this.nodeRef = useRef("node");
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

    onPortMouseDown(ev, portName) {
        if (this.props.onPortMouseDown) {
            this.props.onPortMouseDown({ event: ev, portName: portName, nodeId: this.props.node.id });
        }
    }

    onPointerEnter(ev) {
        if (this.props.onPointerEnter) {
            this.props.onPointerEnter();
        }
    }

    onPointerLeave(ev) {
        if (this.props.onPointerLeave) {
            this.props.onPointerLeave();
        }
    }
}
