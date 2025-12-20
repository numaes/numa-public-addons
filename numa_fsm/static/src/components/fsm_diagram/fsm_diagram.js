/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { FSMNode } from "./fsm_node";
import { FSMTransitionEditor } from "./fsm_transition_editor";
import { FSMStateEditor } from "./fsm_state_editor";
import { FSMNodeCreator } from "./fsm_node_creator";

export class FSMDiagram extends Component {
    static template = "numa_fsm.FSMDiagram";
    static components = { FSMNode, FSMTransitionEditor, FSMStateEditor, FSMNodeCreator };
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");
        this.containerRef = useRef("container");
        this.state = useState({
            nodes: [],
            connections: [],
            transform: { x: 0, y: 0, k: 1 },
            isPanning: false,
            editingNode: null,
            editingNodeType: null,
            newConnection: null,
            showHelp: false,
            isCreatingNode: false,
            creatorPos: { x: 0, y: 0 },
        });

        this.dragStart = { x: 0, y: 0 };
        this.nodeWidth = 150;

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

    loadData(jsonValue) {
        if (!jsonValue) {
            this.state.nodes = [{ id: 'start', type: 'start', x: 50, y: 50, label: 'Start', outcomes: {'out': null}, height: 50 }];
            return;
        }
        try {
            const data = JSON.parse(jsonValue);
            this.state.nodes = data.nodes || [];
            this.state.connections = data.connections || [];
            this.state.transform = data.transform || { x: 0, y: 0, k: 1 };
        } catch (e) { console.error("Invalid FSM Diagram JSON", e); }
    }

    saveData() {
        const data = {
            nodes: this.state.nodes,
            connections: this.state.connections,
            transform: this.state.transform,
        };
        this.props.record.update({ [this.props.name]: JSON.stringify(data) });
    }

    toggleHelp() {
        this.state.showHelp = !this.state.showHelp;
    }

    // --- Interaction ---
    onMouseDown(ev) {
        if (ev.button === 0 && (ev.target.classList.contains('o_fsm_diagram_canvas') || ev.target.classList.contains('o_fsm_viewport'))) {
            this.state.isPanning = true;
            this.dragStart = { x: ev.clientX, y: ev.clientY };
        }
    }

    onMouseMove = (ev) => {
        if (this.state.isPanning) {
            const dx = ev.clientX - this.dragStart.x;
            const dy = ev.clientY - this.dragStart.y;
            this.state.transform.x += dx;
            this.state.transform.y += dy;
            this.dragStart = { x: ev.clientX, y: ev.clientY };
        }
        if (this.state.newConnection) {
            const rect = this.containerRef.el.getBoundingClientRect();
            this.state.newConnection.x2 = (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k;
            this.state.newConnection.y2 = (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k;
        }
    }

    onMouseUp = (ev) => {
        if (this.state.isPanning) {
            this.state.isPanning = false;
            this.saveData();
        }
        if (this.state.newConnection) {
            const targetPort = ev.target.closest('.o_fsm_port_in');
            if (targetPort) {
                const toNodeId = targetPort.dataset.nodeId;
                if (toNodeId !== this.state.newConnection.fromNode) {
                     this.addConnection(this.state.newConnection.fromNode, this.state.newConnection.fromPort, toNodeId);
                }
            }
            this.state.newConnection = null;
        }
    }

    onWheel(ev) {
        ev.preventDefault();
        const zoomIntensity = 0.1;
        const delta = ev.deltaY < 0 ? 1 : -1;
        const newScale = this.state.transform.k + (delta * zoomIntensity);
        if (newScale >= 0.1 && newScale <= 3) {
            this.state.transform.k = newScale;
        }
    }

    onDblClick(ev) {
        if (ev.target.classList.contains('o_fsm_diagram_canvas') || ev.target.classList.contains('o_fsm_viewport')) {
            const rect = this.containerRef.el.getBoundingClientRect();
            this.state.creatorPos = {
                x: (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k,
                y: (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k,
            };
            this.state.isCreatingNode = true;
        }
    }

    addNode(type, x, y, label) {
        const id = 'node_' + Date.now();
        const newNode = { id, type, x, y, label, height: 50 };
        if (type === 'transition') {
            newNode.outcomes = { '__default__': null };
            newNode.code = '# Your Python code here\n# Use set_outcome("outcome_name")';
        } else if (type === 'state') {
            newNode.events = [];
        }
        this.state.nodes.push(newNode);
        this.saveData();
    }

    // --- Node & Editor Handlers ---
    onNodeDblClick(nodeId) {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            this.state.editingNode = node;
            this.state.editingNodeType = node.type;
        }
    }

    onEditorSave(updatedNode) {
        const nodeIndex = this.state.nodes.findIndex(n => n.id === updatedNode.id);
        if (nodeIndex !== -1) this.state.nodes[nodeIndex] = updatedNode;
        this.state.editingNode = null;
        this.state.editingNodeType = null;
        this.saveData();
    }

    onEditorClose() {
        this.state.editingNode = null;
        this.state.editingNodeType = null;
    }

    onNodeMove({ nodeId, x, y }) {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            node.x = x;
            node.y = y;
        }
        this.saveData();
    }

    onNodeResize({ nodeId, height }) {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node && node.height !== height) node.height = height;
    }

    onPortMouseDown({ event, portName, nodeId }) {
        event.stopPropagation();
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (!node) return;

        const rect = event.target.getBoundingClientRect();
        const diagramRect = this.containerRef.el.getBoundingClientRect();
        const x1 = (rect.left - diagramRect.left + rect.width / 2 - this.state.transform.x) / this.state.transform.k;
        const y1 = (rect.top - diagramRect.top + rect.height / 2 - this.state.transform.y) / this.state.transform.k;
        this.state.newConnection = { fromNode: node.id, fromPort: portName, x1, y1, x2: x1, y2: y1 };
    }

    onNodeCreate(type, label, x, y) {
        this.addNode(type, x, y, label);
        this.state.isCreatingNode = false;
    }

    onNodeCreatorClose() {
        this.state.isCreatingNode = false;
    }

    addConnection(fromNodeId, fromPortName, toNodeId) {
        this.state.connections = this.state.connections.filter(c => !(c.fromNodeId === fromNodeId && c.fromPortName === fromPortName));
        const id = `conn_${fromNodeId}_${fromPortName}_${toNodeId}`;
        this.state.connections.push({ id, fromNodeId, fromPortName, toNodeId });
        this.saveData();
    }

    getCurvePath(conn) {
        const fromNode = this.state.nodes.find(n => n.id === conn.fromNodeId);
        const toNode = this.state.nodes.find(n => n.id === conn.toNodeId);
        if (!fromNode || !toNode) return '';

        let portIndex = 0;
        if (fromNode.type === 'state') portIndex = (fromNode.events || []).findIndex(e => e.name === conn.fromPortName);
        else portIndex = Object.keys(fromNode.outcomes || {}).indexOf(conn.fromPortName);
        
        const headerHeight = 30, portHeight = 20;
        const yOffset = headerHeight + 10 + (portIndex * portHeight) + (portHeight / 2);

        const x1 = fromNode.x + this.nodeWidth; 
        const y1 = fromNode.y + yOffset;
        const x2 = toNode.x;
        const y2 = toNode.y + ((toNode.height || 50) / 2); 

        const dx = x2 - x1;
        const curveX = Math.max(Math.abs(dx) * 0.5, 50);
        
        return `M ${x1} ${y1} C ${x1 + curveX} ${y1}, ${x2 - curveX} ${y2}, ${x2} ${y2}`;
    }

    validateDiagram() {
        const errors = [];
        const connectedInputs = new Set(this.state.connections.map(c => c.toNodeId));
        const connectedOutputs = new Set(this.state.connections.map(c => `${c.fromNodeId}-${c.fromPortName}`));

        for (const node of this.state.nodes) {
            const outputs = node.type === 'state' ? (node.events || []).map(e => e.name) : Object.keys(node.outcomes || {});
            for (const portName of outputs) {
                if (!connectedOutputs.has(`${node.id}-${portName}`)) {
                    errors.push(`Node '${node.label}' has an unconnected output port '${portName}'.`);
                }
            }
            if (node.type !== 'start' && !connectedInputs.has(node.id)) {
                errors.push(`Node '${node.label}' has no incoming connection.`);
            }
        }

        if (errors.length > 0) {
            this.notification.add(errors.join('\n'), { type: 'danger', title: 'Validation Errors' });
        } else {
            this.notification.add("Diagram is valid!", { type: 'success' });
        }
    }
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
