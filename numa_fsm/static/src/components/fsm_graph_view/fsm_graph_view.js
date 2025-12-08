/**
 * FSMGraphView - Read-only field widget to visualize FSM diagrams from json_ui_schema
 */
/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

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
                    { id: "state_init", x: 40, y: 200, type: "state", label: "init" },
                    { id: "dec_e_start", x: 260, y: 190, type: "decision", label: "start" },
                    { id: "state_done", x: 460, y: 200, type: "state", label: "done" },
                ];
                this.state.edges = [
                    { id: "e1", source: "state_init", target: "dec_e_start", label: "" },
                    { id: "e2", source: "dec_e_start", target: "state_done", label: "success" },
                ];
                this.state.transform = { ...DEFAULTS.transform };
            }
        };

        onWillStart(() => initFromProps(this.props));
        onWillUpdateProps((nextProps) => initFromProps(nextProps));

        onMounted(() => {
            const root = this.rootEl.el;
            if (!root) return;
            root.addEventListener("mousedown", this.onMouseDown);
            window.addEventListener("mousemove", this.onMouseMove);
            window.addEventListener("mouseup", this.onMouseUp);
            root.addEventListener("wheel", this.onWheel, { passive: false });
        });

        onWillUnmount(() => {
            const root = this.rootEl.el;
            if (root) {
                root.removeEventListener("mousedown", this.onMouseDown);
                root.removeEventListener("wheel", this.onWheel);
            }
            window.removeEventListener("mousemove", this.onMouseMove);
            window.removeEventListener("mouseup", this.onMouseUp);
        });
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

    // Pan & Zoom handlers
    onMouseDown = (ev) => {
        // ignore if scrollbars or text selection
        this._panning.active = true;
        this._panning.lastX = ev.clientX;
        this._panning.lastY = ev.clientY;
        ev.preventDefault();
    };

    onMouseMove = (ev) => {
        if (!this._panning.active) return;
        const dx = ev.clientX - this._panning.lastX;
        const dy = ev.clientY - this._panning.lastY;
        this._panning.lastX = ev.clientX;
        this._panning.lastY = ev.clientY;
        this.state.transform.x += dx;
        this.state.transform.y += dy;
    };

    onMouseUp = () => {
        this._panning.active = false;
    };

    onWheel = (ev) => {
        // Zoom with mouse wheel
        ev.preventDefault();
        const oldK = this.state.transform.k;
        const factor = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
        const newK = clamp(oldK * factor, 0.1, 4);
        this.state.transform.k = newK;
    };
}

registry.category("fields").add("fsm_diagram", {
    component: FSMGraphView,
    supportedTypes: ["char", "text", "html", "json"],
});
