/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
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
    static props = { 
        ...standardFieldProps,
        activeNodeId: { type: String, optional: true },
        readonly: { type: Boolean, optional: true },
    };

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
            isDirty: false,
        });

        this.initialData = null;

        useEffect(() => {
            this.loadData(this.props.value);
        }, () => [this.props.value]);

        onMounted(() => {
            if (!this.props.readonly) {
                window.addEventListener("mousemove", this.onMouseMove);
                window.addEventListener("mouseup", this.onMouseUp);
                window.addEventListener("beforeunload", this.onBeforeUnload);
            }
            if (this.state.nodes.length > 0) {
                setTimeout(() => this.zoomToFit(), 100);
            }
        });

        onWillUnmount(() => {
            if (!this.props.readonly) {
                window.removeEventListener("mousemove", this.onMouseMove);
                window.removeEventListener("mouseup", this.onMouseUp);
                window.removeEventListener("beforeunload", this.onBeforeUnload);
            }
        });
    }

    onBeforeUnload = (ev) => {
        if (this.state.isDirty) {
            ev.preventDefault();
            ev.returnValue = "You have unsaved changes. Are you sure you want to leave?";
        }
    }

    loadData(jsonValue) {
        this.initialData = jsonValue;
        let data = {};
        if (jsonValue) {
            try {
                data = JSON.parse(jsonValue);
            } catch (e) {
                console.error("Invalid FSM Diagram JSON", e);
                data = {};
            }
        }

        if (!data.nodes || data.nodes.length === 0) {
            this.state.nodes = [{ id: 'start', type: 'start', x: 50, y: 150, label: 'Start', outcomes: {'out': null}, height: 50 }];
            this.state.connections = [];
            this.state.transform = { x: 0, y: 0, k: 1 };
        } else {
            this.state.nodes = data.nodes;
            this.state.connections = data.connections || [];
            this.state.transform = data.transform || { x: 0, y: 0, k: 1 };
        }
        this.state.isDirty = false;
    }

    updateData() {
        if (this.props.readonly) return;
        const currentData = JSON.stringify({
            nodes: this.state.nodes,
            connections: this.state.connections,
            transform: this.state.transform,
        });
        // Compare current state with the initial one (as a string)
        if (currentData !== this.initialData) {
            this.state.isDirty = true;
        }
    }

    saveData() {
        if (this.props.readonly) return;
        const data = {
            nodes: this.state.nodes,
            connections: this.state.connections,
            transform: this.state.transform,
        };
        const jsonString = JSON.stringify(data);
        this.props.record.update({ [this.props.name]: jsonString });
        this.initialData = jsonString;
        this.state.isDirty = false;
        this.notification.add("Diagram saved!", { type: 'success' });
    }

    cancelChanges() {
        this.loadData(this.initialData);
    }

    toggleHelp() {
        this.state.showHelp = !this.state.showHelp;
    }

    zoomToFit() {
        if (this.state.nodes.length === 0) return;
        const container = this.containerRef.el;
        if (!container) return;

        const padding = 50;
        const containerWidth = container.clientWidth;
        const containerHeight = container.clientHeight;

        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        this.state.nodes.forEach(node => {
            minX = Math.min(minX, node.x);
            minY = Math.min(minY, node.y);
            maxX = Math.max(maxX, node.x + this.nodeWidth);
            maxY = Math.max(maxY, node.y + (node.height || 100));
        });

        const contentWidth = maxX - minX;
        const contentHeight = maxY - minY;

        if (contentWidth <= 0 || contentHeight <= 0) return;

        const scaleX = (containerWidth - padding * 2) / contentWidth;
        const scaleY = (containerHeight - padding * 2) / contentHeight;
        let scale = Math.min(scaleX, scaleY);
        scale = Math.min(Math.max(scale, 0.1), 1.5);

        const x = (containerWidth - contentWidth * scale) / 2 - minX * scale;
        const y = (containerHeight - contentHeight * scale) / 2 - minY * scale;

        this.state.transform = { x, y, k: scale };
    }

    onMouseDown(ev) {
        if (this.props.readonly) return;
        if (ev.button === 0 && (ev.target.classList.contains('o_fsm_diagram_canvas') || ev.target.classList.contains('o_fsm_viewport'))) {
            this.state.isPanning = true;
            this.dragStart = { x: ev.clientX, y: ev.clientY };
        }
    }

    onMouseMove = (ev) => {
        if (this.props.readonly) return;
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
        if (this.props.readonly) return;
        if (this.state.isPanning) {
            this.state.isPanning = false;
            this.updateData();
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
        if (this.props.readonly) return;
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
        } else if (type === 'end') {
            // End nodes have no outputs
        }
        this.state.nodes.push(newNode);
        this.updateData();
    }

    onNodeDblClick(nodeId) {
        if (this.props.readonly) return;
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            if (node.type === 'end') return;
            this.state.editingNode = node;
            this.state.editingNodeType = node.type;
        }
    }

    onEditorSave(updatedNode) {
        const nodeIndex = this.state.nodes.findIndex(n => n.id === updatedNode.id);
        if (nodeIndex !== -1) this.state.nodes[nodeIndex] = updatedNode;
        this.state.editingNode = null;
        this.state.editingNodeType = null;
        this.updateData();
    }

    onEditorClose() {
        this.state.editingNode = null;
        this.state.editingNodeType = null;
    }

    onNodeMove({ nodeId, x, y, end }) {
        if (this.props.readonly) return;
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            node.x = x;
            node.y = y;
        }
        if (end) {
            this.updateData();
        }
    }

    onNodeResize({ nodeId, height }) {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node && node.height !== height) node.height = height;
        this.updateData();
    }

    onPortMouseDown({ event, portName, nodeId }) {
        if (this.props.readonly) return;
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
        this.updateData();
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
        if (this.props.readonly) return;
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
            if (node.type !== 'start' && node.type !== 'end' && !connectedInputs.has(node.id)) {
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
