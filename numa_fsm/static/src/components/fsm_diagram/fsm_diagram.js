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
            newConnection: null,
        });

        this.dragStart = { x: 0, y: 0 };
        this.nodeWidth = 150; // Standard node width

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
            this.state.nodes = [
                { id: 'start', type: 'start', x: 50, y: 50, label: 'Start', outcomes: {'out': null} }
            ];
            return;
        }
        try {
            const data = JSON.parse(jsonValue);
            this.state.nodes = data.nodes || [];
            this.state.connections = data.connections || [];
            this.state.transform = data.transform || { x: 0, y: 0, k: 1 };
        } catch (e) {
            console.error("Invalid FSM Diagram JSON", e);
        }
    }

    saveData() {
        const data = {
            nodes: this.state.nodes,
            connections: this.state.connections,
            transform: this.state.transform,
        };
        this.props.record.update({ [this.props.name]: JSON.stringify(data) });
    }

    // --- Interaction Handlers ---

    onMouseDown(ev) {
        if (ev.button === 0) {
            if (ev.target === this.containerRef.el) {
                this.state.isDragging = true;
                this.dragStart = { x: ev.clientX, y: ev.clientY };
            }
        }
    }

    onMouseMove = (ev) => {
        if (this.state.isDragging) {
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
        if (this.state.isDragging) {
            this.state.isDragging = false;
            this.saveData();
        }
        if (this.state.newConnection) {
            const targetPort = ev.target.closest('.o_fsm_port_in');
            if (targetPort) {
                const toNodeId = targetPort.dataset.nodeId;
                // Validation: Prevent self-connection and duplicate connections
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
        if (ev.target === this.containerRef.el) {
            const rect = this.containerRef.el.getBoundingClientRect();
            const x = (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k;
            const y = (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k;
            
            const type = prompt("Create 'state' or 'transition'?");
            if (type === 'state' || type === 'transition') {
                const name = prompt(`Enter ${type} Name:`);
                if (name) {
                    this.addNode(type, x, y, name);
                }
            }
        }
    }

    addNode(type, x, y, label) {
        const id = 'node_' + Date.now();
        const newNode = { id, type, x, y, label };
        if (type === 'transition') {
            newNode.outcomes = { '__default__': null };
            newNode.code = '# Your Python code here\n# Use set_outcome("outcome_name") to choose an exit path.';
        } else if (type === 'state') {
            newNode.events = []; // Initialize events array for states
        }
        this.state.nodes.push(newNode);
        this.saveData();
    }

    onNodeDblClick(nodeId) {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            if (node.type === 'transition') {
                this.state.editingNode = node;
            } else if (node.type === 'state') {
                // Simple prompt for state editing for now
                const newName = prompt("Edit State Name:", node.label);
                if (newName) {
                    node.label = newName;
                    // Also allow adding events
                    const eventName = prompt("Add Event (leave empty to skip):");
                    if (eventName) {
                        if (!node.events) node.events = [];
                        node.events.push({ name: eventName });
                    }
                    this.saveData();
                }
            }
        }
    }

    onEditorSave(updatedNode) {
        const nodeIndex = this.state.nodes.findIndex(n => n.id === updatedNode.id);
        if (nodeIndex !== -1) {
            this.state.nodes[nodeIndex] = updatedNode;
        }
        this.state.editingNode = null;
        this.saveData();
    }

    onEditorClose() {
        this.state.editingNode = null;
    }

    onNodeMove(ev) {
        const { nodeId, x, y } = ev.detail;
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            node.x = x;
            node.y = y;
            this.saveData();
        }
    }

    onPortMouseDown(ev, node, portName) {
        ev.stopPropagation();
        const rect = ev.target.getBoundingClientRect();
        const diagramRect = this.containerRef.el.getBoundingClientRect();
        
        // Calculate start position relative to diagram coordinates
        const x1 = (rect.left - diagramRect.left + rect.width / 2 - this.state.transform.x) / this.state.transform.k;
        const y1 = (rect.top - diagramRect.top + rect.height / 2 - this.state.transform.y) / this.state.transform.k;

        this.state.newConnection = {
            fromNode: node.id,
            fromPort: portName,
            x1: x1,
            y1: y1,
            x2: x1, // Initial end point is same as start
            y2: y1,
        };
    }

    addConnection(fromNodeId, fromPortName, toNodeId) {
        // Remove existing connection from this port if any (single output per port)
        this.state.connections = this.state.connections.filter(c => 
            !(c.fromNodeId === fromNodeId && c.fromPortName === fromPortName)
        );
        
        const id = `conn_${fromNodeId}_${fromPortName}_${toNodeId}`;
        this.state.connections.push({ id, fromNodeId, fromPortName, toNodeId });
        this.saveData();
    }

    getCurvePath(conn) {
        const fromNode = this.state.nodes.find(n => n.id === conn.fromNodeId);
        const toNode = this.state.nodes.find(n => n.id === conn.toNodeId);
        if (!fromNode || !toNode) return '';

        // Calculate output port position (Right side)
        // We need to know the index of the port to calculate Y offset
        let portIndex = 0;
        let totalPorts = 0;
        
        if (fromNode.type === 'state') {
            const events = fromNode.events || [];
            portIndex = events.findIndex(e => e.name === conn.fromPortName);
            totalPorts = events.length;
        } else {
            const outcomes = Object.keys(fromNode.outcomes || {});
            portIndex = outcomes.indexOf(conn.fromPortName);
            totalPorts = outcomes.length;
        }
        
        // Estimate header height + padding
        const headerHeight = 30; 
        const portHeight = 20; // Approximate height per port row
        const yOffset = headerHeight + 10 + (portIndex * portHeight) + (portHeight / 2);

        const x1 = fromNode.x + this.nodeWidth; 
        const y1 = fromNode.y + yOffset;

        // Calculate input port position (Left side, centered vertically)
        // Input port is always vertically centered for simplicity in this version
        // Ideally we should calculate node height
        const nodeHeight = 50 + (totalPorts * 20); // Rough estimate
        const x2 = toNode.x;
        const y2 = toNode.y + (nodeHeight / 2); 

        const dx = x2 - x1;
        const dy = y2 - y1;
        const curveX = Math.max(Math.abs(dx) * 0.5, 50); // Ensure some curve even if close
        
        return `M ${x1} ${y1} C ${x1 + curveX} ${y1}, ${x2 - curveX} ${y2}, ${x2} ${y2}`;
    }
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
