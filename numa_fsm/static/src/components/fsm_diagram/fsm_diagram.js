/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillStart, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { useDraggable } from "@web/core/utils/draggable"; // Using the standard Odoo useDraggable
import { FSMNode } from "./fsm_node";
import { FSMTransitionEditor } from "./fsm_transition_editor";
import { FSMStateEditor } from "./fsm_state_editor";
import { FSMNodeCreator } from "./fsm_node_creator";

export class FSMDiagram extends Component {
    static template = "numa_fsm.FSMDiagram";
    static components = { FSMNode, FSMTransitionEditor, FSMStateEditor, FSMNodeCreator };
    static props = {
        ...standardFieldProps,
        readonly: { type: Boolean, optional: true },
    };

    get isReadonly() {
        const record = this.props.record;
        let result;
        if (record?.mode === 'readonly') {
            result = true;
        } else {
            const forceEditableModels = ['fsm.definition', 'conversation.bot'];
            if (record?.resModel && forceEditableModels.includes(record.resModel)) {
                result = false;
            } else {
                result = this.props.readonly;
            }
        }
        console.log(`[FSMDiagram] isReadonly getter: Result: ${result}`);
        return result;
    }

    setup() {
        console.log("[FSMDiagram] setup: Component setup initiated.");
        this.notification = useService("notification");
        this.containerRef = useRef("container");
        this.state = useState({
            nodes: [],
            connections: [],
            transform: { x: 0, y: 0, k: 1 },
            editingNode: null,
            editingNodeType: null,
            newConnection: null,
            isCreatingNode: false,
            creatorPos: { x: 0, y: 0 },
            isDirty: false,
            selectedIds: new Set(),
            dataLoaded: false, // Initial state for data loading
        });

        this.dragMode = null; // 'pan' or 'drag_node'
        this.lastClickInfo = { time: 0, target: null }; // For double-click detection

        // Use the standard Odoo useDraggable hook
        useDraggable({
            ref: this.containerRef,
            elements: ".o_fsm_node, .o_fsm_viewport", // Make nodes and viewport draggable
            ignore: ".o_fsm_port, button, input", // Ignore specific interactive elements
            onDragStart: this.onDragStart,
            onDrag: this.onDrag,
            onDragEnd: this.onDragEnd,
            enable: () => {
                const enabled = !this.isReadonly;
                console.log(`[FSMDiagram] useDraggable enable check: ${enabled}`);
                return enabled;
            },
        });

        onWillStart(async () => {
            console.log("[FSMDiagram] onWillStart: Loading initial data.");
            await this.loadData(this.props.value);
        });

        // This useEffect was causing double load, removed as per previous analysis.
        // Data should only be loaded once on onWillStart or when props.value explicitly changes.
        // If props.value changes, loadData will be called.
        useEffect(() => {
            console.log("[FSMDiagram] useEffect for props.value: Value changed, reloading data.");
            this.loadData(this.props.value);
        }, () => [this.props.value]);


        onMounted(() => {
            console.log("[FSMDiagram] onMounted: Component is now in the DOM.");
            if (this.state.dataLoaded && this.state.nodes.length > 0) {
                console.log("[FSMDiagram] onMounted: Data loaded, scheduling zoomToFit.");
                setTimeout(() => {
                    if (this.containerRef.el) {
                        this.zoomToFit();
                    } else {
                        console.warn("[FSMDiagram] onMounted: containerRef.el is null, cannot zoomToFit.");
                    }
                }, 100);
            } else {
                console.log("[FSMDiagram] onMounted: No data or nodes to zoom to fit.");
            }
        });
    }

    onDragStart = ({ originalEvent, element }) => {
        console.log(`[FSMDiagram] onDragStart: Fired on element '${element.className}'. Original event:`, originalEvent);

        // --- Double-click detection logic ---
        const now = Date.now();
        if (element === this.lastClickInfo.target && (now - this.lastClickInfo.time < 300)) {
            console.log("[FSMDiagram] onDragStart: Double click detected!");
            if (element.classList.contains('o_fsm_node')) {
                console.log(`[FSMDiagram] onDragStart: Double click on node ${element.dataset.nodeId}.`);
                this.onNodeDblClick(element.dataset.nodeId);
            } else if (element.classList.contains('o_fsm_viewport')) {
                console.log("[FSMDiagram] onDragStart: Double click on background (viewport).");
                this.onBackgroundDblClick(originalEvent);
            }
            this.lastClickInfo = { time: 0, target: null }; // Reset for next click sequence
            return false; // Prevent drag from starting for a double-click
        }
        this.lastClickInfo = { time: now, target: element };
        // --- End double-click detection logic ---

        this.dragMode = null; // Reset drag mode
        if (element.classList.contains('o_fsm_node')) {
            this.dragMode = 'drag_node';
            const nodeId = element.dataset.nodeId;
            console.log(`[FSMDiagram] onDragStart: Mode set to 'drag_node' for node ${nodeId}.`);
            // Select node on drag start if not already selected (or shift key not pressed)
            if (!originalEvent.shiftKey && !this.state.selectedIds.has(nodeId)) {
                this.state.selectedIds.clear();
            }
            this.state.selectedIds.add(nodeId);
        } else if (element.classList.contains('o_fsm_viewport')) {
            this.dragMode = 'pan';
            console.log("[FSMDiagram] onDragStart: Mode set to 'pan'.");
            // Clear selection on background pan start if shift key not pressed
            if (!originalEvent.shiftKey) {
                this.state.selectedIds.clear();
            }
        }
        console.log(`[FSMDiagram] onDragStart: Final dragMode: ${this.dragMode}. Selected IDs:`, [...this.state.selectedIds]);
    }

    onDrag = ({ dx, dy, element }) => {
        if (!this.dragMode) {
            console.warn("[FSMDiagram] onDrag: dragMode is null, returning.");
            return;
        }
        console.log(`[FSMDiagram] onDrag: Mode is '${this.dragMode}'. Delta: (${dx}, ${dy}). Element:`, element);
        if (this.dragMode === 'pan') {
            this.state.transform.x += dx;
            this.state.transform.y += dy;
            console.log("[FSMDiagram] onDrag: New transform:", this.state.transform);
        } else if (this.dragMode === 'drag_node') {
            const nodeId = element.dataset.nodeId;
            this.onNodeMove({
                nodeId,
                dx: dx / this.state.transform.k, // Adjust delta by current scale
                dy: dy / this.state.transform.k,
                end: false,
            });
        }
    }

    onDragEnd = ({ element }) => {
        console.log(`[FSMDiagram] onDragEnd: Dragging finished for mode '${this.dragMode}'. Element:`, element);
        if (this.dragMode === 'drag_node') {
            this.onNodeMove({ nodeId: element.dataset.nodeId, end: true }); // Final update and save
        }
        this.dragMode = null;
        console.log("[FSMDiagram] onDragEnd: dragMode reset to null.");
    }

    loadData = (value) => {
        console.log("[FSMDiagram] loadData: Received value:", value);
        try {
            const data = (value && typeof value === 'string' && value.trim() !== "{}") ? JSON.parse(value) : (value || {});
            console.log("[FSMDiagram] loadData: Parsed data:", data);

            this.state.nodes = data.nodes || [];
            this.state.connections = data.connections || [];

            if (this.state.nodes.length === 0) {
                console.log("[FSMDiagram] loadData: No nodes found, creating initial start node.");
                this.state.nodes.push({
                    id: 'start_node', type: 'start', x: 100, y: 100, label: 'Inicio', height: 100, outcomes: { '__default__': null }
                });
            }
            this.state.dataLoaded = true;
            console.log(`[FSMDiagram] loadData: Finished. State has ${this.state.nodes.length} nodes. dataLoaded: ${this.state.dataLoaded}.`);
        } catch (e) {
            console.error("[FSMDiagram] loadData: Error parsing FSM data:", e);
            this.state.nodes = [];
            this.state.connections = [];
            this.state.dataLoaded = true; // Ensure dataLoaded is true even on error to avoid infinite loading states
        }
    }

    updateData = () => {
        console.log("[FSMDiagram] updateData: Saving data to model.");
        if (this.isReadonly) {
            console.log("[FSMDiagram] updateData: Readonly mode, skipping save.");
            return;
        }
        const data = { nodes: this.state.nodes, connections: this.state.connections };
        console.log("[FSMDiagram] updateData: Data to save:", data);
        this.props.record.update({ [this.props.name]: JSON.stringify(data) });
    }

    zoomToFit = () => {
        console.log("[FSMDiagram] zoomToFit: Calculating optimal zoom and pan.");
        if (!this.containerRef.el) {
            console.warn("[FSMDiagram] zoomToFit: containerRef.el is null.");
            return;
        }
        if (this.state.nodes.length === 0) {
            console.log("[FSMDiagram] zoomToFit: No nodes to fit.");
            return;
        }
        const rect = this.containerRef.el.getBoundingClientRect();
        const padding = 50;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        this.state.nodes.forEach(n => {
            minX = Math.min(minX, n.x);
            minY = Math.min(minY, n.y);
            maxX = Math.max(maxX, n.x + 180); // Assuming nodeWidth is 180
            maxY = Math.max(maxY, n.y + (n.height || 50));
        });
        const graphWidth = maxX - minX;
        const graphHeight = maxY - minY;
        const scaleX = graphWidth > 0 ? (rect.width - padding * 2) / graphWidth : 1;
        const scaleY = graphHeight > 0 ? (rect.height - padding * 2) / graphHeight : 1;
        const k = Math.min(Math.max(Math.min(scaleX, scaleY), 0.1), 1.5); // Constrain scale
        this.state.transform = {
            k,
            x: (rect.width / 2) - (k * (minX + graphWidth / 2)),
            y: (rect.height / 2) - (k * (minY + graphHeight / 2)),
        };
        console.log("[FSMDiagram] zoomToFit: New transform:", this.state.transform);
    }

    onWheel = (ev) => {
        console.log("[FSMDiagram] onWheel: Zoom event detected.");
        ev.preventDefault();
        const zoomIntensity = 0.1;
        const delta = ev.deltaY < 0 ? 1 : -1;
        const newScale = this.state.transform.k * (1 + delta * zoomIntensity);
        if (newScale >= 0.1 && newScale <= 3) {
            this.state.transform.k = newScale;
            console.log("[FSMDiagram] onWheel: New scale:", this.state.transform.k);
        } else {
            console.log("[FSMDiagram] onWheel: Scale out of bounds, not applying.");
        }
    }

    onBackgroundDblClick = (ev) => {
        console.log("[FSMDiagram] onBackgroundDblClick: Event fired.", { target: ev.target });
        if (this.isReadonly) {
            console.log("[FSMDiagram] onBackgroundDblClick: Readonly mode, skipping.");
            return;
        }
        if (!this.containerRef.el) {
            console.warn("[FSMDiagram] onBackgroundDblClick: containerRef.el is null.");
            return;
        }
        const rect = this.containerRef.el.getBoundingClientRect();
        this.state.creatorPos = {
            x: (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k,
            y: (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k,
        };
        this.state.isCreatingNode = true;
        console.log("[FSMDiagram] onBackgroundDblClick: Opening node creator at", this.state.creatorPos);
    }

    onNodeMove = ({ nodeId, dx, dy, end }) => {
        console.log(`[FSMDiagram] onNodeMove: Node ${nodeId}, delta (${dx}, ${dy}), end: ${end}.`);
        if (this.isReadonly && !end) {
            console.log("[FSMDiagram] onNodeMove: Readonly mode, skipping move.");
            return;
        }
        if (end) {
            if (!this.isReadonly) this.updateData();
            console.log(`[FSMDiagram] onNodeMove: End of move for node ${nodeId}, data updated.`);
            return;
        }
        const nodesToMove = this.state.selectedIds.has(nodeId)
            ? this.state.nodes.filter(n => this.state.selectedIds.has(n.id))
            : [this.state.nodes.find(n => n.id === nodeId)].filter(Boolean);
        
        if (nodesToMove.length === 0) {
            console.warn(`[FSMDiagram] onNodeMove: No nodes found to move for nodeId ${nodeId}.`);
            return;
        }

        for (const node of nodesToMove) {
            node.x += dx;
            node.y += dy;
            console.log(`[FSMDiagram] onNodeMove: Node ${node.id} new position (${node.x}, ${node.y}).`);
        }
        this.state.isDirty = !this.state.isDirty; // Trigger re-render for connections
    }
    
    onNodeDblClick = (nodeId) => {
        console.log(`[FSMDiagram] onNodeDblClick: Processing for node ${nodeId}.`);
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            this.state.editingNode = JSON.parse(JSON.stringify(node)); // Deep copy for editing
            this.state.editingNodeType = node.type;
            console.log(`[FSMDiagram] onNodeDblClick: Opening editor for node ${nodeId}, type ${node.type}.`);
        } else {
            console.warn(`[FSMDiagram] onNodeDblClick: Node ${nodeId} not found.`);
        }
    }

    onNodeCreate = (type, label, x, y) => {
        console.log(`[FSMDiagram] onNodeCreate: Creating node of type '${type}' with label '${label}' at (${x}, ${y}).`);
        if (this.isReadonly) {
            console.log("[FSMDiagram] onNodeCreate: Readonly mode, skipping creation.");
            return;
        }
        const newNode = { id: `node_${Date.now()}`, type, x, y, label, height: 50 };
        if (type === 'transition') {
            newNode.outcomes = { '__default__': null };
        } else if (type === 'state') {
            newNode.events = [];
        }
        this.state.nodes.push(newNode);
        this.updateData();
        this.state.isCreatingNode = false;
        console.log(`[FSMDiagram] onNodeCreate: Node ${newNode.id} created. Total nodes: ${this.state.nodes.length}.`);
    }
    
    onNodeResize = ({ nodeId, height }) => {
        console.log(`[FSMDiagram] onNodeResize: Node ${nodeId} resized to height ${height}.`);
        if (this.isReadonly) {
            console.log("[FSMDiagram] onNodeResize: Readonly mode, skipping resize.");
            return;
        }
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node && node.height !== height) {
            node.height = height;
            this.updateData();
            console.log(`[FSMDiagram] onNodeResize: Node ${nodeId} height updated and data saved.`);
        } else if (!node) {
            console.warn(`[FSMDiagram] onNodeResize: Node ${nodeId} not found.`);
        }
    }

    onPortMouseDown = ({ event, portName, nodeId }) => {
        console.log(`[FSMDiagram] onPortMouseDown: Port '${portName}' on node ${nodeId} clicked.`);
        if (this.isReadonly) {
            console.log("[FSMDiagram] onPortMouseDown: Readonly mode, skipping connection start.");
            return;
        }
        event.stopPropagation(); // Prevent drag/pan from starting
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (!node) {
            console.warn(`[FSMDiagram] onPortMouseDown: Node ${nodeId} not found.`);
            return;
        }

        const rect = event.target.getBoundingClientRect();
        const diagramRect = this.containerRef.el.getBoundingClientRect();
        const x1 = (rect.left - diagramRect.left + rect.width / 2 - this.state.transform.x) / this.state.transform.k;
        const y1 = (rect.top - diagramRect.top + rect.height / 2 - this.state.transform.y) / this.state.transform.k;
        
        this.state.newConnection = { fromNode: node.id, fromPort: portName, x1, y1, x2: x1, y2: y1 };
        console.log("[FSMDiagram] onPortMouseDown: Starting new connection:", this.state.newConnection);

        const onMouseMove = (moveEv) => {
            const newRect = this.containerRef.el.getBoundingClientRect();
            this.state.newConnection.x2 = (moveEv.clientX - newRect.left - this.state.transform.x) / this.state.transform.k;
            this.state.newConnection.y2 = (moveEv.clientY - newRect.top - this.state.transform.y) / this.state.transform.k;
            // console.log("[FSMDiagram] onPortMouseDown: Connection drawing, x2, y2:", this.state.newConnection.x2, this.state.newConnection.y2);
        };

        const onMouseUp = (upEv) => {
            console.log("[FSMDiagram] onPortMouseDown: Connection mouseUp detected.");
            const targetPort = upEv.target.closest('.o_fsm_port_in');
            if (targetPort) {
                const toNodeId = targetPort.dataset.nodeId;
                if (toNodeId !== this.state.newConnection.fromNode) {
                     this.addConnection(this.state.newConnection.fromNode, this.state.newConnection.fromPort, toNodeId);
                     console.log(`[FSMDiagram] onPortMouseDown: Connection added from ${this.state.newConnection.fromNode} to ${toNodeId}.`);
                } else {
                    console.log("[FSMDiagram] onPortMouseDown: Cannot connect node to itself.");
                }
            } else {
                console.log("[FSMDiagram] onPortMouseDown: No target port found for connection.");
            }
            this.state.newConnection = null;
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
            console.log("[FSMDiagram] onPortMouseDown: Mousemove/mouseup listeners removed.");
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
    }

    addConnection = (fromNodeId, fromPortName, toNodeId) => {
        console.log(`[FSMDiagram] addConnection: Adding connection from ${fromNodeId}:${fromPortName} to ${toNodeId}.`);
        if (this.isReadonly) {
            console.log("[FSMDiagram] addConnection: Readonly mode, skipping.");
            return;
        }
        // Remove existing connection from the same port if any
        this.state.connections = this.state.connections.filter(c => !(c.fromNodeId === fromNodeId && c.fromPortName === fromPortName));
        const id = `conn_${fromNodeId}_${fromPortName}_${toNodeId}`;
        this.state.connections.push({ id, fromNodeId, fromPortName, toNodeId });
        this.updateData();
        console.log(`[FSMDiagram] addConnection: Connection ${id} added. Total connections: ${this.state.connections.length}.`);
    }

    getCurvePath = (conn) => {
        const fromNode = this.state.nodes.find(n => n.id === conn.fromNodeId);
        const toNode = this.state.nodes.find(n => n.id === conn.toNodeId);
        if (!fromNode || !toNode) return '';

        let portIndex = 0;
        if (fromNode.type === 'state') {
            portIndex = (fromNode.events || []).findIndex(e => e.name === conn.fromPortName);
        } else {
            portIndex = Object.keys(fromNode.outcomes || {}).indexOf(conn.fromPortName);
        }
        
        const headerHeight = 30, portHeight = 20;
        const yOffset = headerHeight + 10 + (portIndex * portHeight) + (portHeight / 2);

        const x1 = fromNode.x + 180; // nodeWidth
        const y1 = fromNode.y + yOffset;
        const x2 = toNode.x;
        const y2 = toNode.y + ((toNode.height || 50) / 2); 

        const dx = x2 - x1;
        const curveX = Math.max(Math.abs(dx) * 0.5, 50);
        
        return `M ${x1} ${y1} C ${x1 + curveX} ${y1}, ${x2 - curveX} ${y2}, ${x2} ${y2}`;
    }
    
    showHelp = () => {
        console.log("[FSMDiagram] showHelp: Showing help modal.");
        this.state.showHelp = true;
    }
    hideHelp = () => {
        console.log("[FSMDiagram] hideHelp: Hiding help modal.");
        this.state.showHelp = false;
    }
    validateDiagram = () => {
        console.log("[FSMDiagram] validateDiagram: Triggered.");
        this.notification.add("Validation not implemented yet.", { type: 'info' });
    }
    onNodeCreatorClose = () => {
        console.log("[FSMDiagram] onNodeCreatorClose: Closing node creator.");
        this.state.isCreatingNode = false;
    }
    onEditorClose = () => {
        console.log("[FSMDiagram] onEditorClose: Closing editor.");
        this.state.editingNode = null;
    }
    onEditorSave = (updatedNode) => {
        console.log("[FSMDiagram] onEditorSave: Saving updated node:", updatedNode);
        if (this.isReadonly) {
            console.log("[FSMDiagram] onEditorSave: Readonly mode, skipping save.");
            return;
        }
        const nodeIndex = this.state.nodes.findIndex(n => n.id === updatedNode.id);
        if (nodeIndex !== -1) {
            this.state.nodes[nodeIndex] = updatedNode;
            console.log(`[FSMDiagram] onEditorSave: Node ${updatedNode.id} updated.`);
        } else {
            console.warn(`[FSMDiagram] onEditorSave: Node ${updatedNode.id} not found for update.`);
        }
        this.state.editingNode = null;
        this.updateData();
    };
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
