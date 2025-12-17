/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { FSMNode } from "./fsm_node";
import { FSMTransitionEditor } from "./fsm_transition_editor";

export class FSMDiagram extends Component {
    static template = "numa_fsm.FSMDiagram";
    static components = { FSMNode, FSMTransitionEditor };
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.containerRef = useRef("container");
        this.state = useState({
            nodes: [],
            connections: [],
            transform: { x: 0, y: 0, k: 1 },
            isDragging: false,
            editingNode: null,
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
        }
        this.state.nodes.push(newNode);
        this.saveData();
    }

    onNodeDblClick(nodeId) {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node && node.type === 'transition') {
            this.state.editingNode = node;
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
    
    // ... (resto de los handlers) ...
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
