/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { FSMNode } from "./fsm_node";
import { FSMTransitionEditor } from "./fsm_transition_editor";

export class FSMDiagram extends Component {
    static template = "numa_fsm.FSMDiagram";
    static components = { FSMNode, FSMTransitionEditor };
    static props = { ...standardFieldProps };

    setup() {
        this.containerRef = useRef("container");
        this.state = useState({
            nodes: [],
            connections: [],
            transform: { x: 0, y: 0, k: 1 },
            isDragging: false,
            editingNode: null,
            newConnection: null, // For drawing new connections
        });

        this.dragStart = { x: 0, y: 0 };

        onMounted(() => {
            this.loadData(this.props.value);
            window.addEventListener("mousemove", this.onMouseMove);
            window.addEventListener("mouseup", this.onMouseUp);
        });

        onWillUnmount(() => {
            window.removeEventListener("mousemove", this.onMouseMove);
            window.removeEventListener("mouseup", this.onMouseUp);
        });
    }

    // ... (loadData, saveData, interaction handlers) ...

    onMouseMove = (ev) => {
        if (this.state.isDragging) {
            // Panning logic
        }
        if (this.state.newConnection) {
            // Update the end point of the new connection line
            const rect = this.containerRef.el.getBoundingClientRect();
            this.state.newConnection.x2 = (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k;
            this.state.newConnection.y2 = (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k;
        }
    }

    onMouseUp = (ev) => {
        if (this.state.isDragging) {
            this.state.isDragging = false;
            this.saveData();
        }
        if (this.state.newConnection) {
            const targetPort = ev.target.closest('.o_fsm_port_in');
            if (targetPort) {
                const toNodeId = targetPort.dataset.nodeId;
                this.addConnection(this.state.newConnection.fromNode, this.state.newConnection.fromPort, toNodeId);
            }
            this.state.newConnection = null;
        }
    }

    onPortMouseDown(ev, node, portName) {
        ev.stopPropagation();
        const rect = ev.target.getBoundingClientRect();
        const diagramRect = this.containerRef.el.getBoundingClientRect();
        
        this.state.newConnection = {
            fromNode: node.id,
            fromPort: portName,
            x1: node.x + (rect.left - diagramRect.left + rect.width / 2 - this.state.transform.x) / this.state.transform.k,
            y1: node.y + (rect.top - diagramRect.top + rect.height / 2 - this.state.transform.y) / this.state.transform.k,
            x2: node.x + (rect.left - diagramRect.left + rect.width / 2 - this.state.transform.x) / this.state.transform.k,
            y2: node.y + (rect.top - diagramRect.top + rect.height / 2 - this.state.transform.y) / this.state.transform.k,
        };
    }

    addConnection(fromNodeId, fromPortName, toNodeId) {
        const id = `conn_${fromNodeId}_${fromPortName}_${toNodeId}`;
        this.state.connections.push({ id, fromNodeId, fromPortName, toNodeId });
        this.saveData();
    }

    getCurvePath(conn) {
        const fromNode = this.state.nodes.find(n => n.id === conn.fromNodeId);
        const toNode = this.state.nodes.find(n => n.id === conn.toNodeId);
        if (!fromNode || !toNode) return '';

        // Simplified port position calculation
        const x1 = fromNode.x + 150; // Assume node width
        const y1 = fromNode.y + 20; // Placeholder
        const x2 = toNode.x;
        const y2 = toNode.y + 20; // Placeholder

        const dx = x2 - x1;
        const dy = y2 - y1;
        const curveX = dx * 0.5;
        const curveY = dy * 0;

        return `M ${x1} ${y1} C ${x1 + curveX} ${y1 + curveY}, ${x2 - curveX} ${y2 - curveY}, ${x2} ${y2}`;
    }

    // ... (resto de los métodos) ...
}
