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

    get isReadonly() {
        // In Odoo 18, the record mode is the most reliable way to check if we can edit.
        const record = this.props.record;
        const recordMode = record?.mode; // 'readonly', 'edit', 'create'
        const propsReadonly = this.props.readonly;
        const recordIsReadonly = record?.isReadonly;

        console.log("[FSMDiagram] isReadonly deep check:", {
            recordMode,
            recordIsReadonly,
            propsReadonly,
            resModel: record?.resModel,
            resId: record?.resId,
            record: record
        });

        // ESTRATEGIA AGRESIVA PARA ODOO 18:
        // Si estamos en el modelo fsm.definition, asumimos que NO es readonly 
        // a menos que el record esté explícitamente en modo 'readonly'.
        if (record?.resModel === 'fsm.definition') {
            if (recordMode === 'readonly') return true;
            return false;
        }

        const result = (() => {
            // Priority 1: If we are in 'edit' or 'create' mode, we MUST NOT be readonly
            if (recordMode === 'edit' || recordMode === 'create') {
                return false;
            }
            if (recordMode === 'readonly') {
                return true;
            }

            // Priority 3: record.isReadonly property
            if (recordIsReadonly !== undefined) {
                return recordIsReadonly;
            }

            // Fallback
            if (propsReadonly !== undefined) {
                return propsReadonly;
            }

            return false;
        })();

        console.log("[FSMDiagram] isReadonly result:", result);
        return result;
    }

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
            selectedIds: new Set(),
            dataLoaded: false,
        });

        this.history = [];
        this.nodeWidth = 180;

        this.initialData = null;

        useEffect(() => {
            this.loadData(this.props.value);
        }, () => [this.props.value]);

        onMounted(() => {
            this.env.bus.addEventListener('fsm_node_click', this.onFSMNodeClick.bind(this));
            
            window.addEventListener("mousemove", this.onMouseMove);
            window.addEventListener("mouseup", this.onMouseUp);
            window.addEventListener("keydown", this.onKeyDown);
            window.addEventListener("beforeunload", this.onBeforeUnload);

            if (this.state.nodes.length > 0) {
                setTimeout(() => {
                    if (this.containerRef.el) {
                        this.zoomToFit();
                    }
                }, 100);
            }
        });

        onWillUnmount(() => {
            this.env.bus.removeEventListener('fsm_node_click', this.onFSMNodeClick.bind(this));
            window.removeEventListener("mousemove", this.onMouseMove);
            window.removeEventListener("mouseup", this.onMouseUp);
            window.removeEventListener("keydown", this.onKeyDown);
            window.removeEventListener("beforeunload", this.onBeforeUnload);
        });
    }

    showHelp = () => {
        this.state.showHelp = true;
    }

    hideHelp = () => {
        this.state.showHelp = false;
    }

    loadData(value) {
        if (!value || (typeof value === 'object' && Object.keys(value).length === 0) || value === "{}") {
            this.state.nodes = [{
                id: 'start_node',
                type: 'start',
                x: 100,
                y: 100,
                label: 'Inicio',
                height: 100, // Increased height for start node
                outcomes: { '__default__': null }
            }];
            this.state.connections = [];
            this.state.dataLoaded = true;
            return;
        }
        try {
            const data = typeof value === 'string' ? JSON.parse(value) : value;
            this.state.nodes = data.nodes || [];
            this.state.connections = data.connections || [];

            if (this.state.nodes.length === 0) {
                this.state.nodes = [{
                    id: 'start_node',
                    type: 'start',
                    x: 100,
                    y: 100,
                    label: 'Inicio',
                    height: 100, // Increased height for start node
                    outcomes: { '__default__': null }
                }];
            } else {
                // Ensure start node has correct height if it's there
                const startNode = this.state.nodes.find(n => n.type === 'start');
                if (startNode && (!startNode.height || startNode.height < 100)) {
                    startNode.height = 100;
                }
            }
            
            this.state.dataLoaded = true;
            
            // Initial data for comparison if needed
            if (!this.initialData) {
                this.initialData = JSON.stringify({ nodes: this.state.nodes, connections: this.state.connections });
            }
        } catch (e) {
            console.error("Error parsing FSM data:", e);
            this.state.nodes = [{
                id: 'start_node',
                type: 'start',
                x: 100,
                y: 100,
                label: 'Inicio',
                height: 50,
                outcomes: { '__default__': null }
            }];
            this.state.connections = [];
            this.state.dataLoaded = true;
        }
    }

    updateData() {
        const isReadOnlyState = this.isReadonly;
        if (isReadOnlyState) {
            return;
        }
        const data = {
            nodes: this.state.nodes,
            connections: this.state.connections,
        };
        const value = JSON.stringify(data);
        if (this.props.record && this.props.record.update) {
            this.props.record.update({ [this.props.name]: value });
        } else if (this.props.update) {
            this.props.update(value);
        }
    }

    zoomToFit() {
        if (!this.containerRef.el || this.state.nodes.length === 0) return;

        const rect = this.containerRef.el.getBoundingClientRect();
        const padding = 50;
        
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        
        this.state.nodes.forEach(n => {
            minX = Math.min(minX, n.x);
            minY = Math.min(minY, n.y);
            maxX = Math.max(maxX, n.x + this.nodeWidth);
            maxY = Math.max(maxY, n.y + (n.height || 50));
        });

        const graphWidth = maxX - minX;
        const graphHeight = maxY - minY;
        
        const scaleX = (rect.width - padding * 2) / graphWidth;
        const scaleY = (rect.height - padding * 2) / graphHeight;
        const k = Math.min(Math.max(Math.min(scaleX, scaleY), 0.1), 1.5);

        this.state.transform.k = k;
        this.state.transform.x = (rect.width / 2) - (k * (minX + graphWidth / 2));
        this.state.transform.y = (rect.height / 2) - (k * (minY + graphHeight / 2));
    }

    onFSMNodeClick({ detail }) {
        this.onObjectClick(detail.event, detail.nodeId);
    }

    onKeyDown = (ev) => {
        const isReadOnlyState = this.isReadonly;
        if (isReadOnlyState) return;
        
        // Don't trigger if focus is in an input/textarea
        if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

        if (ev.key === 'Delete' || ev.key === 'Backspace') {
            this.deleteSelected();
        } else if (ev.key === 'z' && (ev.ctrlKey || ev.metaKey)) {
            this.undo();
        }
    }

    takeSnapshot() {
        const snapshot = JSON.stringify({
            nodes: this.state.nodes,
            connections: this.state.connections,
        });
        if (this.history.length === 0 || this.history[this.history.length - 1] !== snapshot) {
            this.history.push(snapshot);
            if (this.history.length > 50) this.history.shift();
        }
    }

    undo() {
        const isReadOnlyState = this.isReadonly;
        if (isReadOnlyState) {
            return;
        }
        if (this.history.length > 1) {
            this.history.pop(); // Remove current state
            const prevState = JSON.parse(this.history[this.history.length - 1]);
            this.state.nodes = prevState.nodes;
            this.state.connections = prevState.connections;
            this.state.selectedIds.clear();
            this.updateData();
        } else if (this.history.length === 1) {
            const prevState = JSON.parse(this.history[0]);
            this.state.nodes = prevState.nodes;
            this.state.connections = prevState.connections;
            this.state.selectedIds.clear();
            this.updateData();
        }
    }

    onObjectClick(ev, id) {
        ev.stopPropagation();
        
        if (ev.shiftKey) {
            if (this.state.selectedIds.has(id)) {
                this.state.selectedIds.delete(id);
            } else {
                this.state.selectedIds.add(id);
            }
        } else {
            this.state.selectedIds.clear();
            this.state.selectedIds.add(id);
        }
    }

    deleteSelected() {
        const isReadOnlyState = this.isReadonly;
        if (isReadOnlyState) {
            return;
        }
        if (this.state.selectedIds.size === 0) return;
        this.takeSnapshot();
        
        const selectedIds = this.state.selectedIds;
        
        // Remove nodes
        this.state.nodes = this.state.nodes.filter(n => !selectedIds.has(n.id));
        
        // Remove connections that are selected OR connected to selected nodes
        this.state.connections = this.state.connections.filter(c => {
            if (selectedIds.has(c.id)) return false;
            if (selectedIds.has(c.fromNodeId) || selectedIds.has(c.toNodeId)) return false;
            return true;
        });
        
        this.state.selectedIds.clear();
        this.updateData();
    }

    onMouseDown(ev) {
        const isReadOnlyState = this.isReadonly;
        const target = ev.target;
        
        // Background elements that should trigger pan or clear selection
        const isToolbar = target.closest('.o_fsm_diagram_toolbar');
        const isNode = target.closest('.o_fsm_node');
        const isConnection = (target.classList && (target.classList.contains('o_fsm_connection') || target.classList.contains('o_fsm_connection_hitbox'))) || target.closest('svg.o_fsm_connections path');
        const isBackground = !isToolbar && !isNode && !isConnection;

        console.log("[FSMDiagram] onMouseDown", {
            readonly: isReadOnlyState,
            target: target.tagName,
            classList: Array.from(target.classList),
            targetClasses: target.className,
            isBackground,
            button: ev.button
        });

        if (ev.button === 0) {
            if (isBackground) {
                if (!ev.shiftKey) {
                    this.state.selectedIds.clear();
                }
                // Pan is allowed even in readonly mode
                this.state.isPanning = true;
                this.dragStart = { x: ev.clientX, y: ev.clientY };
                
                // Set focus to the container to receive keyboard events
                if (this.containerRef.el) {
                    this.containerRef.el.focus();
                }
            }
        }
    }

    onMouseMove = (ev) => {
        const isReadOnlyState = this.isReadonly;
        if (this.state.isPanning) {
            const dx = ev.clientX - this.dragStart.x;
            const dy = ev.clientY - this.dragStart.y;
            this.state.transform.x += dx;
            this.state.transform.y += dy;
            this.dragStart = { x: ev.clientX, y: ev.clientY };
        }
        if (this.state.newConnection) {
            if (isReadOnlyState) {
                this.state.newConnection = null;
                return;
            }
            const rect = this.containerRef.el.getBoundingClientRect();
            this.state.newConnection.x2 = (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k;
            this.state.newConnection.y2 = (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k;
        }
    }

    onMouseUp = (ev) => {
        const isReadOnlyState = this.isReadonly;
        if (this.state.isPanning) {
            this.state.isPanning = false;
        }
        if (this.state.newConnection) {
            const targetPort = ev.target.closest('.o_fsm_port_in');
            if (targetPort && !isReadOnlyState) {
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
        console.log("[FSMDiagram] onWheel", { delta, newScale });
        if (newScale >= 0.1 && newScale <= 3) {
            this.state.transform.k = newScale;
        }
    }

    onDblClick(ev) {
        const isReadOnlyState = this.isReadonly;
        const target = ev.target;
        
        // Robust check for background clicks
        const isToolbar = target.closest('.o_fsm_diagram_toolbar');
        const isNode = target.closest('.o_fsm_node');
        const isConnection = (target.classList && (target.classList.contains('o_fsm_connection') || target.classList.contains('o_fsm_connection_hitbox'))) || target.closest('svg.o_fsm_connections path');

        // If it's not a toolbar, node or connection, it's background
        const isBackground = !isToolbar && !isNode && !isConnection;

        console.log("[FSMDiagram] onDblClick", {
            readonly: isReadOnlyState,
            isToolbar: !!isToolbar,
            isNode: !!isNode,
            isConnection: !!isConnection,
            isBackground,
            target: target.tagName,
            classList: Array.from(target.classList),
            targetClasses: target.className
        });

        if (isBackground) {
            if (isReadOnlyState) {
                console.log("[FSMDiagram] onDblClick - BLOCKED because readonly");
                return;
            }
            const rect = this.containerRef.el.getBoundingClientRect();
            this.state.creatorPos = {
                x: (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k,
                y: (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k,
            };
            console.log("[FSMDiagram] onDblClick - opening node creator at", this.state.creatorPos);
            this.state.isCreatingNode = true;
        }
    }

    addNode(type, x, y, label) {
        this.takeSnapshot();
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
        const isReadOnlyState = this.isReadonly;
        console.log("[FSMDiagram] onNodeDblClick", { nodeId, readonly: isReadOnlyState });
        const node = this.state.nodes.find(n => n.id === nodeId);
        
        if (node) {
            if (node.type === 'end') {
                return;
            }
            this.state.editingNode = { ...node }; // Create a copy to avoid direct mutation
            this.state.editingNodeType = node.type;
            console.log("[FSMDiagram] opening editor for", node.type, "id:", nodeId);
        } else {
            console.warn("[FSMDiagram] node not found for nodeId:", nodeId);
        }
    }

    onEditorSave(updatedNode) {
        const isReadOnlyState = this.isReadonly;
        if (isReadOnlyState) {
            this.state.editingNode = null;
            this.state.editingNodeType = null;
            return;
        }
        this.takeSnapshot();
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

    onNodeMove({ nodeId, dx, dy, end }) {
        const isReadOnlyState = this.isReadonly;
        
        console.log("[FSMDiagram] onNodeMove", { nodeId, dx, dy, end, readonly: isReadOnlyState });

        if (end) {
            if (!isReadOnlyState) {
                this.takeSnapshot();
                this.updateData();
            }
            return;
        }

        // We allow moving nodes visually even in readonly, 
        // so the user can reorganize for viewing.
        // But it won't be saved (blocked in updateData/end).

        const isSelected = this.state.selectedIds.has(nodeId);
        const nodesToMove = isSelected ? 
            this.state.nodes.filter(n => this.state.selectedIds.has(n.id)) : 
            [this.state.nodes.find(n => n.id === nodeId)].filter(Boolean);

        if (nodesToMove.length > 0) {
            for (const node of nodesToMove) {
                node.x += dx;
                node.y += dy;
            }
            
            // Trigger re-render of connections
            this.state.nodes = [...this.state.nodes];
        }
    }

    onNodeResize({ nodeId, height }) {
        const isReadOnlyState = this.isReadonly;
        if (isReadOnlyState) {
            return;
        }
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node && node.height !== height) {
            node.height = height;
            this.updateData();
        }
    }

    onPortMouseDown({ event, portName, nodeId }) {
        const isReadOnlyState = this.isReadonly;
        if (isReadOnlyState) {
            return;
        }
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
        const isReadOnlyState = this.isReadonly;
        console.log("[FSMDiagram] onNodeCreate", { type, label, x, y, readonly: isReadOnlyState });
        if (isReadOnlyState) {
            return;
        }
        this.addNode(type, x, y, label);
        this.state.isCreatingNode = false;
    }

    onNodeCreatorClose() {
        this.state.isCreatingNode = false;
    }

    addConnection(fromNodeId, fromPortName, toNodeId) {
        const isReadOnlyState = this.isReadonly;
        console.log("[FSMDiagram] addConnection called", { fromNodeId, toNodeId, readonly: isReadOnlyState });
        if (isReadOnlyState) {
            console.log("[FSMDiagram] addConnection - BLOCKED because readonly");
            return;
        }
        this.takeSnapshot();
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
        const errors = [];
        const connectedInputs = new Set(this.state.connections.map(c => c.toNodeId));
        const connectedOutputs = new Set(this.state.connections.map(c => `${c.fromNodeId}-${c.fromPortName}`));

        console.log("[FSMDiagram] validateDiagram", { 
            nodes: this.state.nodes.length, 
            connections: this.state.connections.length 
        });

        for (const node of this.state.nodes) {
            const outputs = node.type === 'state' ? (node.events || []).map(e => e.name) : Object.keys(node.outcomes || {});
            
            // Check for unconnected outputs
            for (const portName of outputs) {
                if (!connectedOutputs.has(`${node.id}-${portName}`)) {
                    errors.push(`Nodo '${node.label}' tiene un resultado '${portName}' sin conexión.`);
                }
            }

            // Check for nodes without inputs (except start)
            if (node.type !== 'start' && !connectedInputs.has(node.id)) {
                errors.push(`Nodo '${node.label}' no tiene conexiones de entrada.`);
            }

            // Transition and state MUST have at least one output (except end which has none)
            if (node.type !== 'end' && outputs.length === 0) {
                errors.push(`Nodo '${node.label}' debe tener al menos un resultado.`);
            }
        }

        if (errors.length > 0) {
            console.log("[FSMDiagram] validateDiagram - errors found", errors);
            this.notification.add(errors.join('\n'), { type: 'danger', title: 'Errores de Validación' });
        } else {
            console.log("[FSMDiagram] validateDiagram - success");
            this.notification.add("¡El diagrama es válido!", { type: 'success' });
        }
    }
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
