/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillStart, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { makeDraggableHook } from "@web/core/utils/draggable_hook_builder_owl";
import { FSMNode } from "./fsm_node";
import { FSMTransitionEditor } from "./fsm_transition_editor";
import { FSMStateEditor } from "./fsm_state_editor";
import { FSMNodeCreator } from "./fsm_node_creator";

const useFSMDraggable = makeDraggableHook({
    name: "useFSMDraggable",
    onElementClick: ({ originalEvent, element }) => {
        const component = originalEvent.target.closest(".o_field_fsm_diagram").__owl__.component;
        if (originalEvent.detail === 2) { // Is a double click
            component.onDblClick(originalEvent);
        } else {
            component.onClick(originalEvent);
        }
    },
});

export class FSMDiagram extends Component {
    static template = "numa_fsm.FSMDiagram";
    static components = { FSMNode, FSMTransitionEditor, FSMStateEditor, FSMNodeCreator };
    static props = {
        ...standardFieldProps,
        readonly: { type: Boolean, optional: true },
    };

    get isReadonly() {
        const record = this.props.record;
        if (record?.mode === 'readonly') return true;
        const forceEditableModels = ['fsm.definition', 'conversation.bot'];
        if (record?.resModel && forceEditableModels.includes(record.resModel)) return false;
        return this.props.readonly;
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
        });

        this.dragMode = null;

        useFSMDraggable({
            ref: this.containerRef,
            elements: ".o_fsm_node, .o_fsm_viewport",
            ignore: ".o_fsm_port, button, input",
            onDragStart: this.onDragStart,
            onDrag: this.onDrag,
            onDragEnd: this.onDragEnd,
            enable: () => !this.isReadonly,
        });

        onWillStart(async () => this.loadData(this.props.value));
        useEffect(() => this.loadData(this.props.value), () => [this.props.value]);

        onMounted(() => {
            if (this.state.nodes.length > 0) {
                setTimeout(() => {
                    if (this.containerRef.el) this.zoomToFit();
                }, 100);
            }
        });
    }

    onDragStart = ({ originalEvent, element }) => {
        this.dragMode = null;
        if (element.classList.contains('o_fsm_node')) {
            this.dragMode = 'drag_node';
        } else if (element.classList.contains('o_fsm_viewport')) {
            this.dragMode = 'pan';
        }
    }

    onDrag = ({ dx, dy, element }) => {
        if (!this.dragMode) return;
        if (this.dragMode === 'pan') {
            this.state.transform.x += dx;
            this.state.transform.y += dy;
        } else if (this.dragMode === 'drag_node') {
            const nodeId = element.dataset.nodeId;
            this.onNodeMove({
                nodeId,
                dx: dx / this.state.transform.k,
                dy: dy / this.state.transform.k,
                end: false,
            });
        }
    }

    onDragEnd = ({ element }) => {
        if (this.dragMode === 'drag_node') {
            this.onNodeMove({ nodeId: element.dataset.nodeId, end: true });
        }
        this.dragMode = null;
    }

    onClick = (ev) => {
        const target = ev.target;
        const isNode = target.closest('.o_fsm_node');
        const isBackground = target.classList.contains('o_fsm_viewport');

        if (isNode) {
            const nodeId = isNode.dataset.nodeId;
            if (!ev.shiftKey && !this.state.selectedIds.has(nodeId)) {
                this.state.selectedIds.clear();
            }
            if (this.state.selectedIds.has(nodeId)) {
                this.state.selectedIds.delete(nodeId);
            } else {
                this.state.selectedIds.add(nodeId);
            }
        } else if (isBackground) {
            if (!ev.shiftKey) {
                this.state.selectedIds.clear();
            }
        }
    }

    onDblClick = (ev) => {
        const target = ev.target;
        const isNode = target.closest('.o_fsm_node');
        const isBackground = target.classList.contains('o_fsm_viewport');

        if (isNode) {
            this.onNodeDblClick(isNode.dataset.nodeId);
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
            const data = (value && typeof value === 'string' && value.trim() !== "{}") ? JSON.parse(value) : (value || {});
            this.state.nodes = data.nodes || [];
            this.state.connections = data.connections || [];
            if (this.state.nodes.length === 0) {
                this.state.nodes.push({
                    id: 'start_node', type: 'start', x: 100, y: 100, label: 'Inicio', height: 100, outcomes: { '__default__': null }
                });
            }
        } catch (e) {
            console.error("Error parsing FSM data:", e);
            this.state.nodes = [];
            this.state.connections = [];
        }
    }

    updateData = () => {
        if (this.isReadonly) return;
        const data = { nodes: this.state.nodes, connections: this.state.connections };
        this.props.record.update({ [this.props.name]: JSON.stringify(data) });
    }

    zoomToFit = () => {
        if (!this.containerRef.el || this.state.nodes.length === 0) return;
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

    onNodeMove = ({ nodeId, dx, dy, end }) => {
        if (this.isReadonly && !end) return;
        if (end) {
            if (!this.isReadonly) this.updateData();
            return;
        }
        const nodesToMove = this.state.selectedIds.has(nodeId)
            ? this.state.nodes.filter(n => this.state.selectedIds.has(n.id))
            : [this.state.nodes.find(n => n.id === nodeId)].filter(Boolean);
        for (const node of nodesToMove) {
            node.x += dx;
            node.y += dy;
        }
        this.state.isDirty = !this.state.isDirty;
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
        const newNode = { id: `node_${Date.now()}`, type, x, y, label, height: 50 };
        if (type === 'transition') {
            newNode.outcomes = { '__default__': null };
        } else if (type === 'state') {
            newNode.events = [];
        }
        this.state.nodes.push(newNode);
        this.updateData();
        this.state.isCreatingNode = false;
    }
    
    onNodeResize = ({ nodeId, height }) => {
        if (this.isReadonly) return;
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (node && node.height !== height) {
            node.height = height;
            this.updateData();
        }
    }

    onPortMouseDown = ({ event, portName, nodeId }) => {
        if (this.isReadonly) return;
        event.stopPropagation();
        const node = this.state.nodes.find(n => n.id === nodeId);
        if (!node) return;

        const rect = event.target.getBoundingClientRect();
        const diagramRect = this.containerRef.el.getBoundingClientRect();
        const x1 = (rect.left - diagramRect.left + rect.width / 2 - this.state.transform.x) / this.state.transform.k;
        const y1 = (rect.top - diagramRect.top + rect.height / 2 - this.state.transform.y) / this.state.transform.k;
        
        this.state.newConnection = { fromNode: node.id, fromPort: portName, x1, y1, x2: x1, y2: y1 };

        const onMouseMove = (moveEv) => {
            const newRect = this.containerRef.el.getBoundingClientRect();
            this.state.newConnection.x2 = (moveEv.clientX - newRect.left - this.state.transform.x) / this.state.transform.k;
            this.state.newConnection.y2 = (moveEv.clientY - newRect.top - this.state.transform.y) / this.state.transform.k;
        };

        const onMouseUp = (upEv) => {
            const targetPort = upEv.target.closest('.o_fsm_port_in');
            if (targetPort) {
                const toNodeId = targetPort.dataset.nodeId;
                if (toNodeId !== this.state.newConnection.fromNode) {
                     this.addConnection(this.state.newConnection.fromNode, this.state.newConnection.fromPort, toNodeId);
                }
            }
            this.state.newConnection = null;
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
    }

    addConnection = (fromNodeId, fromPortName, toNodeId) => {
        if (this.isReadonly) return;
        this.state.connections = this.state.connections.filter(c => !(c.fromNodeId === fromNodeId && c.fromPortName === fromPortName));
        const id = `conn_${fromNodeId}_${fromPortName}_${toNodeId}`;
        this.state.connections.push({ id, fromNodeId, fromPortName, toNodeId });
        this.updateData();
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
    
    showHelp = () => this.state.showHelp = true;
    hideHelp = () => this.state.showHelp = false;
    validateDiagram = () => this.notification.add("Validation not implemented yet.", { type: 'info' });
    onNodeCreatorClose = () => this.state.isCreatingNode = false;
    onEditorClose = () => this.state.editingNode = null;
    onEditorSave = (updatedNode) => {
        if (this.isReadonly) return;
        const nodeIndex = this.state.nodes.findIndex(n => n.id === updatedNode.id);
        if (nodeIndex !== -1) {
            this.state.nodes[nodeIndex] = updatedNode;
        }
        this.state.editingNode = null;
        this.updateData();
    };
}

registry.category("fields").add("fsm_diagram", {
    component: FSMDiagram,
});
