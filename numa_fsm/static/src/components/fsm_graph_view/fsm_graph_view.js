/**
 * FSMGraphView - Interactive field widget to visualize and edit FSM diagrams
 */
/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _lt } from "@web/core/l10n/translation";

const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

const DEFAULTS = {
    nodeSizes: {
        state: { w: 140, h: 60 },
        decision: { w: 100, h: 100 },
    },
    transform: { x: 0, y: 0, k: 1 },
};

function parseSchema(value) {
    try {
        if (!value) return null;
        if (typeof value === "string") {
            const v = value.trim();
            if (!v) return null;
            return JSON.parse(v);
        }
        if (typeof value === "object") {
            return value;
        }
    } catch (e) {
        // ignore parse errors; will fallback to default layout
    }
    return null;
}

export class FSMGraphView extends Component {
    static template = "numa_fsm.FSMGraphView";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.rootEl = useRef("root");
        this.canvasEl = useRef("canvas");

        this.state = useState({
            nodes: [], // {id, x, y, type, label}
            edges: [], // {id, source, target, label}
            transform: { ...DEFAULTS.transform },
            selected: null, // {type: 'node'|'edge', id}
            drag: { active: false, nodeId: null, offsetX: 0, offsetY: 0 },
            connect: { active: false, fromId: null, toPos: { x: 0, y: 0 } },
            meta: {
                debug_mode: null,
                current_state: null,
                is_simulation: false,
                last_status: null,
            },
        });

        this._panning = {
            active: false,
            lastX: 0,
            lastY: 0,
        };

        const initFromProps = (props) => {
            const schema = parseSchema(props.value);
            if (schema && (schema.nodes || schema.edges)) {
                const nodes = Array.isArray(schema.nodes) ? schema.nodes : [];
                const edges = Array.isArray(schema.edges) ? schema.edges : [];
                const transform = schema.transform || DEFAULTS.transform;
                this.state.nodes = nodes;
                this.state.edges = edges;
                this.state.transform = { x: transform.x || 0, y: transform.y || 0, k: clamp(transform.k || 1, 0.1, 4) };
            } else {
                // Fallback: a simple example layout
                this.state.nodes = [
                    { id: "state_init", x: 40, y: 200, type: "state", label: "init", subtype: "normal" },
                    { id: "dec_e_start", x: 260, y: 190, type: "decision", label: "start", code: "# outcome = 'success'\n", outcomes: ["success"] },
                    { id: "state_done", x: 460, y: 200, type: "state", label: "done", subtype: "final" },
                ];
                this.state.edges = [
                    { id: "e1", source: "state_init", target: "dec_e_start", label: "" },
                    { id: "e2", source: "dec_e_start", target: "state_done", label: "success" },
                ];
                this.state.transform = { ...DEFAULTS.transform };
            }

            // Debug/meta coming from record (fsm.instance or any model embedding this widget)
            try {
                const data = props.record && props.record.data ? props.record.data : {};
                this.state.meta.debug_mode = data.debug_mode || null;
                this.state.meta.current_state = data.current_state || null;
                this.state.meta.is_simulation = !!data.is_simulation;
                // Optional: allow integrators to compute/store the last log status in a field
                this.state.meta.last_status = data.last_log_status || data._last_execution_status || null;
            } catch (e) {
                // ignore
            }
        };

        onWillStart(() => initFromProps(this.props));
        onWillUpdateProps((nextProps) => initFromProps(nextProps));

        onMounted(() => {
            const root = this.rootEl.el;
            if (!root) return;
            root.addEventListener("mousedown", this.onMouseDownBackground);
            window.addEventListener("mousemove", this.onMouseMove);
            window.addEventListener("mouseup", this.onMouseUp);
            root.addEventListener("wheel", this.onWheel, { passive: false });
            window.addEventListener("keydown", this.onKeyDown);
        });

        onWillUnmount(() => {
            const root = this.rootEl.el;
            if (root) {
                root.removeEventListener("mousedown", this.onMouseDownBackground);
                root.removeEventListener("wheel", this.onWheel);
            }
            window.removeEventListener("mousemove", this.onMouseMove);
            window.removeEventListener("mouseup", this.onMouseUp);
            window.removeEventListener("keydown", this.onKeyDown);
        });
    }

    // ------------------------------------------------------------------
    // Styling helpers based on debug state
    // ------------------------------------------------------------------
    _isPaused() {
        const dm = this.state.meta.debug_mode;
        return dm === 'step' || dm === 'paused';
    }

    _isCurrentNode(node) {
        const cs = this.state.meta.current_state;
        if (!cs) return false;
        // Prefer matching by label (state name). Fallback to id.
        return (node.label && node.label === cs) || node.id === cs;
    }

    getNodeCss(node) {
        const classes = [];
        if (this._isCurrentNode(node)) {
            if (this.state.meta.last_status === 'error') {
                classes.push('error-current');
            } else if (this._isPaused()) {
                classes.push('paused-current');
            }
        }
        return classes.join(' ');
    }

    getNodeById(id) {
        return this.state.nodes.find((n) => n.id === id);
    }

    getNodeCenter(node) {
        const size = node.type === "decision" ? DEFAULTS.nodeSizes.decision : DEFAULTS.nodeSizes.state;
        return { cx: node.x + size.w / 2, cy: node.y + size.h / 2 };
    }

    edgePath(edge) {
        const src = this.getNodeById(edge.source);
        const dst = this.getNodeById(edge.target);
        if (!src || !dst) return "";
        const { cx: x1, cy: y1 } = this.getNodeCenter(src);
        const { cx: x2, cy: y2 } = this.getNodeCenter(dst);
        const dx = x2 - x1;
        const curvature = 0.5; // simple factor
        const c1x = x1 + dx * curvature;
        const c1y = y1;
        const c2x = x2 - dx * curvature;
        const c2y = y2;
        return `M ${x1},${y1} C ${c1x},${c1y} ${c2x},${c2y} ${x2},${y2}`;
    }

    edgeMid(edge) {
        const src = this.getNodeById(edge.source);
        const dst = this.getNodeById(edge.target);
        if (!src || !dst) return { x: 0, y: 0 };
        const { cx: x1, cy: y1 } = this.getNodeCenter(src);
        const { cx: x2, cy: y2 } = this.getNodeCenter(dst);
        return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
    }

    ghostPath() {
        if (!this.state.connect.active || !this.state.connect.fromId) return '';
        const from = this.getNodeById(this.state.connect.fromId);
        if (!from) return '';
        const { cx: x1, cy: y1 } = this.getNodeCenter(from);
        const { x: x2, y: y2 } = this.state.connect.toPos;
        const dx = x2 - x1;
        const curvature = 0.5;
        const c1x = x1 + dx * curvature;
        const c1y = y1;
        const c2x = x2 - dx * curvature;
        const c2y = y2;
        return `M ${x1},${y1} C ${c1x},${c1y} ${c2x},${c2y} ${x2},${y2}`;
    }

    // Coordinate helpers
    screenToCanvas(clientX, clientY) {
        const rect = this.rootEl.el.getBoundingClientRect();
        const x = (clientX - rect.left - this.state.transform.x) / this.state.transform.k;
        const y = (clientY - rect.top - this.state.transform.y) / this.state.transform.k;
        return { x, y };
    }

    // Background Pan & Zoom handlers
    onMouseDownBackground = (ev) => {
        if (ev.target.closest('.fsm-node') || ev.target.closest('.fsm-controls') || ev.target.closest('.fsm-sidebar')) return;
        this._panning.active = true;
        this._panning.lastX = ev.clientX;
        this._panning.lastY = ev.clientY;
        this.state.selected = null;
        ev.preventDefault();
    };

    onMouseMove = (ev) => {
        if (this._panning.active) {
            const dx = ev.clientX - this._panning.lastX;
            const dy = ev.clientY - this._panning.lastY;
            this._panning.lastX = ev.clientX;
            this._panning.lastY = ev.clientY;
            this.state.transform.x += dx;
            this.state.transform.y += dy;
            return;
        }
        if (this.state.drag.active && this.state.drag.nodeId) {
            const node = this.getNodeById(this.state.drag.nodeId);
            if (node) {
                const { x, y } = this.screenToCanvas(ev.clientX, ev.clientY);
                node.x = x - this.state.drag.offsetX;
                node.y = y - this.state.drag.offsetY;
            }
            return;
        }
        if (this.state.connect.active) {
            const { x, y } = this.screenToCanvas(ev.clientX, ev.clientY);
            this.state.connect.toPos = { x, y };
            return;
        }
    };

    onMouseUp = () => {
        this._panning.active = false;
        this.state.drag = { active: false, nodeId: null, offsetX: 0, offsetY: 0 };
        this.state.connect.active = false;
    };

    onWheel = (ev) => {
        // Zoom with mouse wheel
        ev.preventDefault();
        const oldK = this.state.transform.k;
        const factor = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
        const newK = clamp(oldK * factor, 0.1, 4);
        this.state.transform.k = newK;
    };

    onKeyDown = (ev) => {
        if (ev.key === 'Delete' || ev.key === 'Backspace') {
            this.deleteSelected();
        }
        if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') {
            ev.preventDefault();
            this.save();
        }
    };

    // Node interactions
    onNodeMouseDown = (node, ev) => {
        // start dragging node (unless clicking on port)
        if (ev.target.closest('.fsm-port')) return;
        const { x, y } = this.screenToCanvas(ev.clientX, ev.clientY);
        this.state.drag = { active: true, nodeId: node.id, offsetX: x - node.x, offsetY: y - node.y };
        this.state.selected = { type: 'node', id: node.id };
        ev.stopPropagation();
    };

    onStartConnect = (node, ev) => {
        const { x, y } = this.screenToCanvas(ev.clientX, ev.clientY);
        this.state.connect = { active: true, fromId: node.id, toPos: { x, y } };
        this.state.selected = { type: 'node', id: node.id };
        ev.stopPropagation();
    };

    onNodeMouseUp = (node, ev) => {
        // If we were connecting and mouseup over a node => create edge per rules
        if (this.state.connect.active && this.state.connect.fromId) {
            const from = this.getNodeById(this.state.connect.fromId);
            const to = node;
            if (from && to && from.id !== to.id) {
                // Enforce rules: state->decision, decision->state, optional state->state
                const ok = (from.type === 'state' && to.type === 'decision') ||
                           (from.type === 'decision' && to.type === 'state') ||
                           (from.type === 'state' && to.type === 'state');
                if (ok) {
                    const id = `e_${Date.now()}_${Math.floor(Math.random()*1000)}`;
                    let label = '';
                    if (from.type === 'decision' && to.type === 'state') {
                        // try to auto-pick first outcome name if exists on decision
                        label = from.outcomes && from.outcomes.length ? from.outcomes[0] : '';
                    }
                    if (from.type === 'state' && to.type === 'state') {
                        // default sugar: create default outcome transition
                        label = 'default';
                    }
                    this.state.edges.push({ id, source: from.id, target: to.id, label });
                }
            }
        }
        this.state.connect.active = false;
        ev.stopPropagation();
    };

    onEdgeClick = (edge, ev) => {
        this.state.selected = { type: 'edge', id: edge.id };
        ev.stopPropagation();
    };

    // Outcomes helpers for inspector
    addOutcome = (node) => {
        node.outcomes = node.outcomes || [];
        node.outcomes.push('new_outcome');
    };

    removeOutcome = (node, index) => {
        if (!node.outcomes) return;
        node.outcomes.splice(index, 1);
    };

    updateOutcome = (node, index, value) => {
        node.outcomes = node.outcomes || [];
        if (index >= 0 && index < node.outcomes.length) {
            node.outcomes[index] = value;
        }
    };

    addState = () => {
        const id = `state_${Date.now()}`;
        const center = this.screenToCanvas(this.rootEl.el.clientWidth / 2, this.rootEl.el.clientHeight / 2);
        this.state.nodes.push({ id, x: center.x - 70, y: center.y - 30, type: 'state', label: 'state', subtype: 'normal' });
        this.state.selected = { type: 'node', id };
    };

    addDecision = () => {
        const id = `dec_${Date.now()}`;
        const center = this.screenToCanvas(this.rootEl.el.clientWidth / 2 + 50, this.rootEl.el.clientHeight / 2);
        this.state.nodes.push({ id, x: center.x - 50, y: center.y - 50, type: 'decision', label: 'event', code: "# outcome = 'success'\n", outcomes: ['success'] });
        this.state.selected = { type: 'node', id };
    };

    deleteSelected = () => {
        const sel = this.state.selected;
        if (!sel) return;
        if (sel.type === 'node') {
            const idx = this.state.nodes.findIndex(n => n.id === sel.id);
            if (idx >= 0) {
                // remove connected edges too
                this.state.edges = this.state.edges.filter(e => e.source !== sel.id && e.target !== sel.id);
                this.state.nodes.splice(idx, 1);
            }
        } else if (sel.type === 'edge') {
            const i = this.state.edges.findIndex(e => e.id === sel.id);
            if (i >= 0) this.state.edges.splice(i, 1);
        }
        this.state.selected = null;
    };

    // Helpers for template
    isSelectedNode(node) {
        return this.state.selected && this.state.selected.type === 'node' && this.state.selected.id === node.id;
    }
    isSelectedEdge(edge) {
        return this.state.selected && this.state.selected.type === 'edge' && this.state.selected.id === edge.id;
    }

    // Serialization: save UI and Logic schemas
    save = () => {
        const ui = {
            nodes: this.state.nodes.map(n => ({ id: n.id, x: n.x, y: n.y, type: n.type, label: n.label, subtype: n.subtype, code: n.code, outcomes: n.outcomes })),
            edges: this.state.edges.map(e => ({ id: e.id, source: e.source, target: e.target, label: e.label })),
            transform: this.state.transform,
        };
        const uiStr = JSON.stringify(ui);
        if (this.props.update) {
            this.props.update(uiStr);
        }

        // Build logic schema
        const states = {};
        const transitions = {};
        const nodeById = Object.fromEntries(this.state.nodes.map(n => [n.id, n]));

        // collect states
        for (const n of this.state.nodes) {
            if (n.type === 'state') {
                const stateName = n.label || n.id;
                states[stateName] = { subtype: n.subtype || 'normal' };
            }
        }

        // helper to ensure dict
        const ensure = (obj, key) => (obj[key] = obj[key] || {});

        // for each edge state->decision, create transition entry
        for (const e of this.state.edges) {
            const src = nodeById[e.source];
            const dst = nodeById[e.target];
            if (!src || !dst) continue;

            // state -> decision (event)
            if (src.type === 'state' && dst.type === 'decision') {
                const stateName = src.label || src.id;
                const eventName = dst.label || 'event';
                const transState = ensure(transitions, stateName);
                const decCode = dst.code || '';
                // Collect outcomes from all decision outgoing edges
                const decisionOutEdges = this.state.edges.filter(ed => ed.source === dst.id);
                const outcomes = {};
                for (const od of decisionOutEdges) {
                    const t = nodeById[od.target];
                    if (t && t.type === 'state') {
                        const outcomeName = od.label || 'ok';
                        const targetStateName = t.label || t.id;
                        outcomes[outcomeName] = targetStateName;
                    }
                }
                transState[eventName] = { code: decCode, outcomes };
            }

            // state -> state (sugar): create a trivial transition with default outcome
            if (src.type === 'state' && dst.type === 'state') {
                const stateName = src.label || src.id;
                const eventName = e.label || 'default';
                const transState = ensure(transitions, stateName);
                const outcome = e.label || 'default';
                const targetStateName = dst.label || dst.id;
                transState[eventName] = { code: `outcome = '${outcome}'`, outcomes: { [outcome]: targetStateName } };
            }
        }

        const logic = { states, transitions };
        const logicStr = JSON.stringify(logic);
        // update sibling field if possible
        if (this.props.record && this.props.record.update) {
            this.props.record.update({ json_logic_schema: logicStr });
        }
    };
}

registry.category("fields").add("fsm_diagram", {
    component: FSMGraphView,
    supportedTypes: ["char", "text", "html", "json"],
});
