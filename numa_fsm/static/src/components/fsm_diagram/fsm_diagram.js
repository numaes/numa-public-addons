/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillStart, onWillUnmount } from "@odoo/owl";
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
        readonly: { type: Boolean, optional: true },
    };

    get isReadonly() {
        const record = this.props.record;
        let result;
        if (record?.mode === 'readonly') {
            result = true;
        } else {
            // Force editability for definition models unless explicitly in readonly mode
            const forceEditableModels = ['fsm.definition', 'conversation.bot', 'conversation.analysis.report'];
            if (record?.resModel && (forceEditableModels.includes(record.resModel) || record.resModel.startsWith('fsm.'))) {
                result = false;
            } else {
                result = this.props.readonly;
            }
        }
        
        // DEBUG: If it's still readonly but we are in fsm.definition, bypass it.
        if (result && (record?.resModel === 'fsm.definition' || record?.resModel === 'conversation.bot') && record?.mode !== 'readonly') {
            result = false;
        }

        console.log("[FSMDiagram] isReadonly result:", result, "deep check:", {
            recordMode: record?.mode,
            resModel: record?.resModel,
            propsReadonly: this.props.readonly,
            resId: record?.resId
        });
        return result;
    }

    setup() {
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
            dataLoaded: false,
        });

        this.dragState = null;

        onWillStart(async () => {
            await this.loadData(this.props.value);
        });

        onMounted(() => {
            console.log("[FSMDiagram] onMounted");
            if (this.state.nodes.length > 0) {
                setTimeout(() => {
                    if (this.containerRef.el) {
                        this.zoomToFit();
                    }
                }, 100);
            }
            this.boundMouseMove = this.onGlobalMouseMove.bind(this);
            this.boundMouseUp = this.onGlobalMouseUp.bind(this);
            this.boundKeyDown = this.onKeyDown.bind(this);

            window.addEventListener('mousemove', this.boundMouseMove);
            window.addEventListener('mouseup', this.boundMouseUp);
            window.addEventListener('keydown', this.boundKeyDown);
        });

        onWillUnmount(() => {
            console.log("[FSMDiagram] onWillUnmount");
            window.removeEventListener('mousemove', this.boundMouseMove);
            window.removeEventListener('mouseup', this.boundMouseUp);
            window.removeEventListener('keydown', this.boundKeyDown);
        });
    }

    onMouseDown = (ev) => {
        const target = ev.target;
        const nodeEl = target.closest('.o_fsm_node');
        const isToolbar = target.closest('.o_fsm_diagram_toolbar');
        const isEditor = target.closest('.o_fsm_editors');
        const isPort = target.closest('.o_fsm_port');
        const isConnection = target.closest('.o_fsm_connection_hitbox') || target.closest('.o_fsm_connection');

        console.log("[FSMDiagram] onMouseDown", {
            target: target.tagName,
            classes: target.className,
            isNode: !!nodeEl,
            isPort: !!isPort,
            isConnection: !!isConnection,
            isBackground: !nodeEl && !isPort && !isToolbar && !isEditor && !isConnection,
            button: ev.button,
            readonly: this.isReadonly
        });

        if (isToolbar || isEditor || isPort) return;

        // Ensure container has focus for keyboard events
        if (this.containerRef.el) {
            this.containerRef.el.focus();
        }

        const startX = ev.clientX;
        const startY = ev.clientY;
        const now = Date.now();

        // Manual double click detection
        if (this.lastClick && (now - this.lastClick.time < 300) && (Math.abs(startX - this.lastClick.x) < 5) && (Math.abs(startY - this.lastClick.y) < 5)) {
             console.log("[FSMDiagram] Manual double click detected");
             this.onDblClick(ev);
             this.lastClick = null;
             // ev.preventDefault(); // Might be needed?
             return;
        }
        this.lastClick = { x: startX, y: startY, time: now };

        if (nodeEl) {
            ev.preventDefault();
            const nodeId = nodeEl.dataset.nodeId;
            console.log("[FSMDiagram] Node selected for drag:", nodeId);
            if (!ev.shiftKey && !this.state.selectedIds.has(nodeId)) {
                this.state.selectedIds.clear();
            }
            this.state.selectedIds.add(nodeId);

            this.dragState = {
                type: 'node',
                nodeId,
                startX,
                startY,
                initialNodes: this.state.nodes.filter(n => this.state.selectedIds.has(n.id)).map(n => ({ id: n.id, x: n.x, y: n.y })),
            };
        } else if (isConnection) {
            const connId = isConnection.dataset.connId;
            if (!ev.shiftKey) this.state.selectedIds.clear();
            if (connId) this.state.selectedIds.add(connId);
            this.dragState = null;
        } else {
            ev.preventDefault();
            if (!ev.shiftKey) this.state.selectedIds.clear();
            console.log("[FSMDiagram] Starting pan");
            this.dragState = {
                type: 'pan',
                startX,
                startY,
                initialX: this.state.transform.x,
                initialY: this.state.transform.y,
            };
        }
    }

    onGlobalMouseMove = (ev) => {
        if (!this.dragState) return;
        // console.log("[FSMDiagram] onGlobalMouseMove", this.dragState.type);

        const dx = ev.clientX - this.dragState.startX;
        const dy = ev.clientY - this.dragState.startY;
        
        if (this.dragState.type === 'pan') {
            this.state.transform.x = this.dragState.initialX + dx;
            this.state.transform.y = this.dragState.initialY + dy;
        } else if (this.dragState.type === 'node') {
            const k = this.state.transform.k;
            this.state.nodes = this.state.nodes.map(node => {
                if (this.state.selectedIds.has(node.id)) {
                    const initial = this.dragState.initialNodes.find(n => n.id === node.id);
                    if (initial) {
                        return { ...node, x: initial.x + (dx / k), y: initial.y + (dy / k) };
                    }
                }
                return node;
            });
            this.state.isDirty = !this.state.isDirty;
        }
    }

    onGlobalMouseUp = () => {
        if (!this.dragState) return;
        const dragType = this.dragState.type;
        console.log("[FSMDiagram] onGlobalMouseUp", {
            type: dragType,
            nodeId: this.dragState.nodeId,
            readonly: this.isReadonly
        });
        if (dragType === 'node' && !this.isReadonly) {
            this.updateData();
        }
        this.dragState = null;
    }

    onKeyDown = (ev) => {
        if (ev.key === 'Delete' || ev.key === 'Backspace') {
            if (this.isReadonly) return;
            const selectedNodes = this.state.nodes.filter(n => this.state.selectedIds.has(n.id));
            const selectedConns = this.state.connections.filter(c => this.state.selectedIds.has(c.id));
            
            if (selectedNodes.length > 0 || selectedConns.length > 0) {
                console.log("[FSMDiagram] Deleting selected elements");
                // Remove connections associated with deleted nodes
                const nodeIds = new Set(selectedNodes.map(n => n.id));
                this.state.connections = this.state.connections.filter(c => 
                    !this.state.selectedIds.has(c.id) && 
                    !nodeIds.has(c.fromNodeId) && 
                    !nodeIds.has(c.toNodeId)
                );
                this.state.nodes = this.state.nodes.filter(n => !this.state.selectedIds.has(n.id));
                this.state.selectedIds.clear();
                this.updateData();
            }
        }
    }

    onDblClick = (ev) => {
        const target = ev.target;
        const nodeEl = target.closest('.o_fsm_node');
        const isBackground = !nodeEl && (target.closest('.o_fsm_viewport') || target.closest('.o_fsm_diagram_container') || target.tagName === 'svg' || target.tagName === 'path');

        console.log("[FSMDiagram] onDblClick", {
            target: target.tagName,
            classes: target.className,
            isNode: !!nodeEl,
            isBackground,
            readonly: this.isReadonly
        });

        if (nodeEl) {
            console.log("[FSMDiagram] Node double clicked, opening editor:", nodeEl.dataset.nodeId);
            this.onNodeDblClick(nodeEl.dataset.nodeId);
        } else if (isBackground && !this.isReadonly) {
            const rect = this.containerRef.el.getBoundingClientRect();
            this.state.creatorPos = {
                x: (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k,
                y: (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k,
            };
            console.log("[FSMDiagram] opening node creator at", this.state.creatorPos);
            this.state.isCreatingNode = true;
        }
    }
    
    loadData = (value) => {
        try {
            const data = (value && typeof value === 'string' && value.trim() !== "{}") ? JSON.parse(value) : (value || {});

            this.state.nodes = data.nodes || [];
            this.state.connections = data.connections || [];

            if (this.state.nodes.length === 0) {
                this.state.nodes.push({
                    id: 'start_node', type: 'start', x: 100, y: 100, label: 'Inicio', outcomes: { '__default__': null }
                });
            }
            this.state.dataLoaded = true;
        } catch (e) {
            console.error("[FSMDiagram] loadData: Error parsing FSM data:", e);
            this.state.nodes = [];
            this.state.connections = [];
            this.state.dataLoaded = true;
        }
    }

    updateData = () => {
        if (this.isReadonly) return;
        const data = { nodes: this.state.nodes, connections: this.state.connections };
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
            maxX = Math.max(maxX, n.x + 180);
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

    onNodeMove = ({ nodeId, dx, dy, end }) => {
        if (this.isReadonly && !end) return;
        if (end) {
            if (!this.isReadonly) this.updateData();
            return;
        }
        
        // Use functional mapping for better reactiveness
        this.state.nodes = this.state.nodes.map(node => {
            if (this.state.selectedIds.has(node.id) || node.id === nodeId) {
                return { ...node, x: node.x + dx, y: node.y + dy };
            }
            return node;
        });
        this.state.isDirty = !this.state.isDirty; // Trigger re-render for connections
    }
    
    onNodeDblClick = (nodeId) => {
        console.log("[FSMDiagram] onNodeDblClick", nodeId);
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            this.state.editingNode = JSON.parse(JSON.stringify(node)); // Deep copy for editing
            this.state.editingNodeType = node.type;
            console.log("[FSMDiagram] opening editor for", node.type);
        }
    }

    onNodeCreate = (type, label, x, y) => {
        if (this.isReadonly) return;
        const id = `node_${Date.now()}`;
        console.log("[FSMDiagram] addNode", { type, label, x, y, id });
        const newNode = { 
            id, 
            type, 
            x, 
            y, 
            label: label || (type === 'state' ? 'New State' : 'New Transition'), 
            height: 50 
        };
        if (type === 'transition' || type === 'start') {
            newNode.outcomes = { '__default__': null };
        } else if (type === 'state') {
            newNode.events = [];
        }
        this.state.nodes = [...this.state.nodes, newNode];
        this.updateData();
        this.state.isCreatingNode = false;
    }
    
    onNodeResize = ({ nodeId, height }) => {
        if (this.isReadonly) return;
        const nodeIndex = this.state.nodes.findIndex(n => n.id === nodeId);
        if (nodeIndex !== -1 && this.state.nodes[nodeIndex].height !== height) {
            // Immutable update to trigger connection re-render
            const newNodes = [...this.state.nodes];
            newNodes[nodeIndex] = { ...newNodes[nodeIndex], height };
            this.state.nodes = newNodes;
            this.updateData();
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
        this.state.editingNodeType = null;
    }
    onEditorSave = (updatedNode) => {
        if (this.isReadonly) return;
        const nodeIndex = this.state.nodes.findIndex(n => n.id === updatedNode.id);
        if (nodeIndex !== -1) {
            this.state.nodes = this.state.nodes.map(n => n.id === updatedNode.id ? { ...updatedNode } : n);
        }
        this.state.editingNode = null;
        this.state.editingNodeType = null;
        this.updateData();
    };
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
