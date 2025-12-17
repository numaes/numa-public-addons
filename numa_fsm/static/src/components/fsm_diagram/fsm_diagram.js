/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { FSMNode } from "./fsm_node";

export class FSMDiagram extends Component {
    static template = "numa_fsm.FSMDiagram";
    static components = { FSMNode };
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.containerRef = useRef("container");
        this.state = useState({
            nodes: [],
            connections: [],
            transform: { x: 0, y: 0, k: 1 }, // Pan and Zoom
            isDragging: false,
            selection: null,
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
            // Default initial state
            this.state.nodes = [
                { id: 'start', type: 'start', x: 50, y: 50, label: 'Start' }
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
        if (ev.button === 0) { // Left click
            if (ev.target === this.containerRef.el) {
                // Start Panning
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
    }

    onMouseUp = (ev) => {
        if (this.state.isDragging) {
            this.state.isDragging = false;
            this.saveData(); // Save view state (pan/zoom)
        }
    }

    onWheel(ev) {
        ev.preventDefault();
        const zoomIntensity = 0.1;
        const delta = ev.deltaY < 0 ? 1 : -1;
        const newScale = this.state.transform.k + (delta * zoomIntensity);
        
        // Limit zoom
        if (newScale >= 0.1 && newScale <= 3) {
            // Zoom towards mouse pointer logic could go here
            this.state.transform.k = newScale;
        }
    }

    // --- Node Handlers ---
    
    onNodeMove(nodeId, x, y) {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            node.x = x;
            node.y = y;
        }
    }
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
