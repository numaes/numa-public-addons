/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillStart, onWillUnmount, useExternalListener } from "@odoo/owl";
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
        
        // Forced readonly if in production state
        if (record?.data?.state === 'production') {
            return true;
        }

        // Si estamos en un modelo de FSM o Bot, forzamos editabilidad a menos que el registro esté explícitamente bloqueado
        const forceEditableModels = ['fsm.definition', 'conversation.bot', 'conversation.analysis.report'];
        const isForceModel = record?.resModel && (forceEditableModels.includes(record.resModel) || record.resModel.startsWith('fsm.'));
        
        if (isForceModel) {
            return record.mode === 'readonly' && this.props.readonly;
        }
        
        return record?.mode === 'readonly' || !!this.props.readonly;
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
            selectedIds: new Set(),
            dataLoaded: false,
            connectingTargetId: null,
            hoveredId: null,
            showHelp: false,
        });

        this.dragState = null;
        this.historyStack = [];
        this.maxHistory = 50;

        onWillStart(async () => {
            await this.loadData(this.props.value);
        });

        onMounted(() => {
            if (this.state.nodes.length > 0) {
                setTimeout(() => {
                    if (this.containerRef.el) {
                        this.zoomToFit();
                    }
                }, 500);
            }
        });

        useExternalListener(document, "pointermove", this.onGlobalMouseMove);
        useExternalListener(document, "pointerup", this.onGlobalMouseUp);
        useExternalListener(document, "keydown", this.onKeyDown);
    }

    takeSnapshot() {
        if (this.historyStack.length >= this.maxHistory) {
            this.historyStack.shift();
        }
        this.historyStack.push(JSON.stringify({
            nodes: this.state.nodes,
            connections: this.state.connections
        }));
    }

    undo = () => {
        if (this.isReadonly || this.historyStack.length === 0) return;
        const snapshot = this.historyStack.pop();
        const data = JSON.parse(snapshot);
        this.state.nodes = data.nodes;
        this.state.connections = data.connections;
        this.state.selectedIds.clear();
        this.updateData();
    }

    onMouseDown = (ev) => {
        const target = ev.target;
        const nodeEl = target.closest('.o_fsm_node');
        const isToolbar = target.closest('.o_fsm_diagram_toolbar');
        const isEditor = target.closest('.o_fsm_editors');
        const isPort = target.closest('.o_fsm_port');
        const isConnection = target.closest('.o_fsm_connection_hitbox') || target.closest('.o_fsm_connection');

        if (isToolbar || isEditor) return;
        if (ev.button !== 0) return;
        
        if (this.containerRef.el) {
            this.containerRef.el.focus();
        }

        // Port Click logic (starting a connection)
        if (isPort && isPort.classList.contains('o_fsm_port_out')) {
            if (this.isReadonly) return;
            const nodeId = isPort.dataset.nodeId;
            const portName = isPort.dataset.portName;
            this.onPortMouseDown({ event: ev, portName, nodeId });
            return;
        }

        // Double click detection
        const startX = ev.clientX;
        const startY = ev.clientY;
        const now = Date.now();
        if (this.lastClick && (now - this.lastClick.time < 300) && (Math.abs(startX - this.lastClick.x) < 5) && (Math.abs(startY - this.lastClick.y) < 5)) {
             this.onDblClick(ev);
             this.lastClick = null;
             return;
        }
        this.lastClick = { x: startX, y: startY, time: now };

        if (target.setPointerCapture && ev.pointerId !== undefined) {
            try { target.setPointerCapture(ev.pointerId); } catch (e) {}
        }

        if (nodeEl) {
            const nodeId = nodeEl.dataset.nodeId;
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
            if (!ev.shiftKey) this.state.selectedIds.clear();
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
        ev.preventDefault();

        const dx = ev.clientX - this.dragState.startX;
        const dy = ev.clientY - this.dragState.startY;
        
        if (this.dragState.type === 'pan') {
            this.state.transform = {
                ...this.state.transform,
                x: this.dragState.initialX + dx,
                y: this.dragState.initialY + dy
            };
        } else if (this.dragState.type === 'node') {
            if (this.isReadonly) return;
            const k = this.state.transform.k;
            this.state.nodes = this.state.nodes.map(node => {
                if (this.state.selectedIds.has(node.id)) {
                    const initial = this.dragState.initialNodes.find(n => n.id === node.id);
                    if (initial) {
                        return { ...node, x: Math.round(initial.x + (dx / k)), y: Math.round(initial.y + (dy / k)) };
                    }
                }
                return node;
            });
        } else if (this.dragState.type === 'connection') {
            const rect = this.containerRef.el.getBoundingClientRect();
            const k = this.state.transform.k;
            const x2 = (ev.clientX - rect.left - this.state.transform.x) / k;
            const y2 = (ev.clientY - rect.top - this.state.transform.y) / k;

            this.state.newConnection = { ...this.state.newConnection, x2, y2 };

            const elements = document.elementsFromPoint(ev.clientX, ev.clientY);
            const targetNodeEl = elements.find(el => el.closest('.o_fsm_node'))?.closest('.o_fsm_node');
            const targetNodeId = targetNodeEl?.dataset?.nodeId;
            
            if (targetNodeId && targetNodeId !== this.state.newConnection.fromNode && targetNodeId !== 'start_node') {
                this.state.connectingTargetId = targetNodeId;
            } else {
                this.state.connectingTargetId = null;
            }
        }
    }

    onGlobalMouseUp = (ev) => {
        const target = ev.target;
        if (target && target.releasePointerCapture && ev.pointerId !== undefined) {
            try { target.releasePointerCapture(ev.pointerId); } catch (e) {}
        }

        if (!this.dragState) return;
        const dragType = this.dragState.type;

        if (dragType === 'node' && !this.isReadonly) {
            const dx = ev.clientX - this.dragState.startX;
            const dy = ev.clientY - this.dragState.startY;
            if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
                this.takeSnapshot();
                this.updateData();
            }
        } else if (dragType === 'connection' && !this.isReadonly) {
            const elements = document.elementsFromPoint(ev.clientX, ev.clientY);
            let targetNodeId = elements.find(el => el.closest('.o_fsm_port_in'))?.closest('.o_fsm_port_in')?.dataset.nodeId;
            
            if (!targetNodeId) {
                const targetNodeEl = elements.find(el => el.closest('.o_fsm_node'))?.closest('.o_fsm_node');
                if (targetNodeEl && targetNodeEl.dataset.nodeId !== 'start_node') {
                    targetNodeId = targetNodeEl.dataset.nodeId;
                }
            }
            
            if (targetNodeId && targetNodeId !== this.state.newConnection.fromNode) {
                this.takeSnapshot();
                this.addConnection(this.state.newConnection.fromNode, this.state.newConnection.fromPort, targetNodeId);
            }
            this.state.newConnection = null;
            this.state.connectingTargetId = null;
        }
        this.dragState = null;
    }

    onKeyDown = (ev) => {
        if ((ev.key === 'Delete' || ev.key === 'Backspace') && !this.isReadonly) {
            const selectedNodes = this.state.nodes.filter(n => this.state.selectedIds.has(n.id) && n.type !== 'start');
            const selectedConns = this.state.connections.filter(c => this.state.selectedIds.has(c.id));
            
            if (selectedNodes.length > 0 || selectedConns.length > 0) {
                this.takeSnapshot();
                const nodeIds = new Set(selectedNodes.map(n => n.id));
                this.state.connections = this.state.connections.filter(c => 
                    !this.state.selectedIds.has(c.id) && 
                    !nodeIds.has(c.fromNodeId) && 
                    !nodeIds.has(c.toNodeId)
                );
                this.state.nodes = this.state.nodes.filter(n => !this.state.selectedIds.has(n.id) || n.type === 'start');
                this.state.selectedIds.clear();
                this.updateData();
            }
        } else if (ev.key === 'z' && (ev.ctrlKey || ev.metaKey)) {
            ev.preventDefault();
            this.undo();
        }
    }

    onDblClick = (ev) => {
        const target = ev.target;
        const nodeEl = target.closest('.o_fsm_node');
        const isBackground = !nodeEl && (target.closest('.o_fsm_viewport') || target.closest('.o_fsm_diagram_container') || target.tagName === 'svg' || target.tagName === 'path');

        if (nodeEl) {
            this.onNodeDblClick(nodeEl.dataset.nodeId);
        } else if (isBackground && !this.isReadonly) {
            const rect = this.containerRef.el.getBoundingClientRect();
            this.state.creatorPos = {
                x: (ev.clientX - rect.left - this.state.transform.x) / this.state.transform.k,
                y: (ev.clientY - rect.top - this.state.transform.y) / this.state.transform.k,
            };
            this.state.isCreatingNode = true;
        }
    }
    
    loadData = (value) => {
        try {
            let data = value;
            if (typeof value === 'string') {
                if (value.trim() === "" || value.trim() === "{}") {
                    data = {};
                } else {
                    data = JSON.parse(value);
                }
            }
            
            this.state.nodes = data?.nodes || [];
            this.state.connections = data?.connections || [];

            if (this.state.nodes.length === 0) {
                this.state.nodes.push({
                    id: 'start_node', type: 'start', x: 100, y: 100, label: 'Inicio', outcomes: { '__default__': null }
                });
            }
            this.state.dataLoaded = true;
        } catch (e) {
            this.state.nodes = [{ id: 'start_node', type: 'start', x: 100, y: 100, label: 'Inicio', outcomes: { '__default__': null } }];
            this.state.connections = [];
            this.state.dataLoaded = true;
        }
    }

    updateData = async () => {
        if (this.isReadonly) return;
        const data = { nodes: this.state.nodes, connections: this.state.connections };
        
        try {
            await this.props.record.update({ [this.props.name]: data });
            if (this.props.record.model && this.props.record.model.root) {
                this.props.record.model.root.isDirty = true;
            }
        } catch (err) {
            // Fallback for non-json fields or older odoo expectations
            const jsonVal = JSON.stringify(data);
            await this.props.record.update({ [this.props.name]: jsonVal });
        }
    }

    zoomToFit = () => {
        if (!this.containerRef.el || this.state.nodes.length === 0) return;
        const rect = this.containerRef.el.getBoundingClientRect();
        const padding = 50;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        this.state.nodes.forEach(n => {
            const w = n.type === 'start' ? 100 : (n.type === 'end' ? 80 : 180);
            minX = Math.min(minX, n.x);
            minY = Math.min(minY, n.y);
            maxX = Math.max(maxX, n.x + w);
            maxY = Math.max(maxY, n.y + (n.height || 50));
        });
        const graphWidth = maxX - minX;
        const graphHeight = maxY - minY;
        const scaleX = graphWidth > 0 ? (rect.width - padding * 2) / graphWidth : 1;
        const scaleY = graphHeight > 0 ? (rect.height - padding * 2) / graphHeight : 1;
        const k = Math.min(Math.max(Math.min(scaleX, scaleY), 0.1), 1.5);
        this.state.transform = {
            k,
            x: (rect.width / 2) - (k * (minX + graphWidth / 2)),
            y: (rect.height / 2) - (k * (minY + graphHeight / 2)),
        };
    }

    onWheel = (ev) => {
        ev.preventDefault();
        const zoomIntensity = 0.1;
        const delta = ev.deltaY < 0 ? 1 : -1;
        const newScale = this.state.transform.k * (1 + delta * zoomIntensity);
        if (newScale >= 0.1 && newScale <= 3) {
            this.state.transform.k = newScale;
        }
    }

    onPortMouseDown = ({ event, portName, nodeId }) => {
        event.preventDefault();
        event.stopPropagation();
        
        const fromNode = this.state.nodes.find(n => n.id === nodeId);
        const HEADER_HEIGHT = 30;
        const BODY_PADDING = 10;
        const PORT_HEIGHT = 20;
        const NODE_WIDTH = 180;
        const BORDER_OFFSET = 1;

        let x1, y1;
        if (fromNode.type === 'start') {
            x1 = fromNode.x + 100;
            y1 = fromNode.y + 50;
        } else {
            let portIndex = 0;
            if (fromNode.type === 'state') {
                portIndex = (fromNode.events || []).findIndex(e => e.name === portName);
            } else {
                portIndex = Object.keys(fromNode.outcomes || {}).indexOf(portName);
            }
            if (portIndex === -1) portIndex = 0;
            x1 = fromNode.x + NODE_WIDTH;
            y1 = fromNode.y + BORDER_OFFSET + HEADER_HEIGHT + BODY_PADDING + (portIndex * PORT_HEIGHT) + (PORT_HEIGHT / 2);
        }

        this.state.newConnection = { fromNode: nodeId, fromPort: portName, x1, y1, x2: x1, y2: y1 };
        this.dragState = { type: 'connection', startX: event.clientX, startY: event.clientY };
        
        if (event.target.setPointerCapture && event.pointerId !== undefined) {
            try { event.target.setPointerCapture(event.pointerId); } catch (e) {}
        }
    }

    onNodeDblClick = (nodeId) => {
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node) {
            this.state.editingNode = JSON.parse(JSON.stringify(node));
            this.state.editingNodeType = node.type;
        }
    }

    onNodeCreate = (type, label, x, y) => {
        if (this.isReadonly) return;
        this.takeSnapshot();
        const id = `node_${Date.now()}`;
        const newNode = { 
            id, type, x: Math.round(x), y: Math.round(y), label,
            height: type === 'start' ? 100 : (type === 'end' ? 80 : 50)
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
        const nodeIndex = this.state.nodes.findIndex(n => n.id === nodeId);
        if (nodeIndex !== -1 && this.state.nodes[nodeIndex].height !== height) {
            this.state.nodes = this.state.nodes.map(n => n.id === nodeId ? { ...n, height } : n);
        }
    }

    addConnection = (fromNodeId, fromPortName, toNodeId) => {
        if (this.isReadonly) return;
        const filteredConns = this.state.connections.filter(c => !(c.fromNodeId === fromNodeId && c.fromPortName === fromPortName));
        const id = `conn_${fromNodeId}_${fromPortName}_${toNodeId}`;
        this.state.connections = [...filteredConns, { id, fromNodeId, fromPortName, toNodeId }];
        this.updateData();
    }

    getCurvePath = (conn) => {
        const fromNode = this.state.nodes.find(n => n.id === conn.fromNodeId);
        const toNode = this.state.nodes.find(n => n.id === conn.toNodeId);
        if (!fromNode || !toNode) return '';

        const HEADER_HEIGHT = 30;
        const BODY_PADDING = 10;
        const PORT_HEIGHT = 20;
        const NODE_WIDTH = 180;
        const BORDER_OFFSET = 1;

        let x1, y1;
        if (fromNode.type === 'start') {
            x1 = fromNode.x + 100;
            y1 = fromNode.y + 50;
        } else {
            let portIndex = 0;
            if (fromNode.type === 'state') {
                portIndex = (fromNode.events || []).findIndex(e => e.name === conn.fromPortName);
            } else {
                portIndex = Object.keys(fromNode.outcomes || {}).indexOf(conn.fromPortName);
            }
            if (portIndex === -1) portIndex = 0;
            x1 = fromNode.x + NODE_WIDTH;
            y1 = fromNode.y + BORDER_OFFSET + HEADER_HEIGHT + BODY_PADDING + (portIndex * PORT_HEIGHT) + (PORT_HEIGHT / 2);
        }

        const x2 = toNode.x;
        let y2;
        if (toNode.type === 'start') {
            y2 = toNode.y + 50;
        } else if (toNode.type === 'end') {
            y2 = toNode.y + 40;
        } else {
            const h = toNode.height || 50;
            y2 = toNode.y + (h / 2);
        }

        const dx = x2 - x1;
        const curveX = Math.max(Math.abs(dx) * 0.5, 50);
        
        // Use Math.round for clean rendering
        const rx1 = Math.round(x1);
        const ry1 = Math.round(y1);
        const rx2 = Math.round(x2);
        const ry2 = Math.round(y2);
        const rcx1 = Math.round(x1 + curveX);
        const rcx2 = Math.round(x2 - curveX);

        return `M ${rx1} ${ry1} C ${rcx1} ${ry1}, ${rcx2} ${ry2}, ${rx2} ${ry2}`;
    }
    
    showHelp = () => { this.state.showHelp = true; }
    hideHelp = () => { this.state.showHelp = false; }

    onElementPointerEnter = (id) => {
        this.state.hoveredId = id;
    }

    onElementPointerLeave = () => {
        this.state.hoveredId = null;
    }

    validateDiagram = () => {
        let errors = [];
        const nodes = this.state.nodes;
        const conns = this.state.connections;

        nodes.forEach(node => {
            if (node.type === 'start') {
                const hasOut = conns.some(c => c.fromNodeId === node.id);
                if (!hasOut) errors.push("El nodo de Inicio debe estar conectado.");
            } else if (node.type === 'state') {
                const hasIn = conns.some(c => c.toNodeId === node.id);
                if (!hasIn) errors.push(`El estado "${node.label}" no tiene entradas.`);
                (node.events || []).forEach(evt => {
                    const connected = conns.some(c => c.fromNodeId === node.id && c.fromPortName === evt.name);
                    if (!connected) errors.push(`El evento "${evt.name}" del estado "${node.label}" no está conectado.`);
                });
            } else if (node.type === 'transition') {
                const hasIn = conns.some(c => c.toNodeId === node.id);
                if (!hasIn) errors.push(`La transición "${node.label}" no tiene entradas.`);
                Object.keys(node.outcomes || {}).forEach(out => {
                    const connected = conns.some(c => c.fromNodeId === node.id && c.fromPortName === out);
                    if (!connected) errors.push(`El resultado "${out}" de la transición "${node.label}" no está conectado.`);
                });
            }
        });

        if (errors.length > 0) {
            this.notification.add(errors.join("\n"), { type: 'danger', sticky: true, title: "Errores de Validación" });
        } else {
            this.notification.add("¡Diagrama válido!", { type: 'success' });
        }
    }

    onNodeCreatorClose = () => { this.state.isCreatingNode = false; }
    onEditorClose = () => { this.state.editingNode = null; this.state.editingNodeType = null; }
    onEditorSave = (updatedNode) => {
        if (this.isReadonly) return;
        this.takeSnapshot();
        this.state.nodes = this.state.nodes.map(n => n.id === updatedNode.id ? { ...updatedNode } : n);
        this.onEditorClose();
        this.updateData();
    };

    onValidateClick = async () => {
        try {
            await this.props.record.model.root.save();
            await this.props.record.model.orm.call(
                'fsm.definition',
                'action_validate',
                [this.props.record.resId]
            );
            await this.props.record.model.root.load();
        } catch (err) {
            // Error handled by odoo
        }
    }
}

registry.category("fields").add("fsm_diagram", { component: FSMDiagram });
