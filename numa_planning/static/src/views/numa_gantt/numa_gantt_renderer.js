/** @odoo-module **/

import { Component, useRef, onMounted, onPatched, useState } from "@odoo/owl";

export class NumaGanttRenderer extends Component {
    static template = "numa_planning.NumaGanttRenderer";
    static props = ["model"];

    setup() {
        this.canvasRef = useRef("canvas");
        this.treeRef = useRef("tree");
        this.timelineRef = useRef("timeline");
        this.state = useState({
            hoveredNodeId: null,
            draggingNodeId: null,
        });

        onMounted(() => {
            this.draw();
            this.syncScroll();
        });
        onPatched(() => this.draw());
    }

    syncScroll() {
        const tree = this.treeRef.el;
        const timeline = this.timelineRef.el;
        if (!tree || !timeline) return;

        timeline.addEventListener("scroll", () => {
            tree.scrollTop = timeline.scrollTop;
        });
        tree.addEventListener("scroll", () => {
            timeline.scrollTop = tree.scrollTop;
        });
    }

    /**
     * Coordinate System: Time -> Pixels
     * X = (Date - StartDate) * PixelsPerUnit(scale)
     * Y = NodeIndex * RowHeight
     */
    getPixelsPerDay() {
        const scales = {
            'day': 100,
            'week': 20,
            'month': 5
        };
        return scales[this.props.model.state.scale] || 20;
    }

    dateToX(date) {
        const diff = new Date(date) - this.props.model.state.startDate;
        return (diff / (1000 * 60 * 60 * 24)) * this.getPixelsPerDay();
    }

    draw() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        const timeline = this.timelineRef.el;
        if (timeline) {
            // High DPI support and matching scroll dimensions
            const pixelsPerDay = this.getPixelsPerDay();
            const { startDate, endDate, nodes } = this.props.model.state;
            const days = (endDate - startDate) / (1000 * 60 * 60 * 24);
            
            canvas.width = days * pixelsPerDay;
            canvas.height = Math.max(nodes.length * 40 + 150, timeline.clientHeight);
        }

        const ctx = canvas.getContext("2d");
        const { nodes } = this.props.model.state;
        const width = canvas.width;
        const height = canvas.height;

        ctx.clearRect(0, 0, width, height);

        // Draw Grid
        this.drawGrid(ctx, width, height);

        // Draw Dependencies
        this.drawDependencies(ctx);

        // Draw Bars
        nodes.forEach((node, index) => {
            this.drawBar(ctx, node, index);
        });

        // Draw Histogram
        this.drawHistogram(ctx, width, height);
    }

    drawHistogram(ctx, width, height) {
        const histHeight = 100;
        const top = height - histHeight;
        const resources = this.props.model.state.resources || [];
        
        ctx.fillStyle = "rgba(240, 240, 240, 0.9)";
        ctx.fillRect(0, top, width, histHeight);
        ctx.strokeStyle = "#ccc";
        ctx.strokeRect(0, top, width, histHeight);

        if (resources.length === 0) return;

        const pixelsPerDay = this.getPixelsPerDay();
        resources.forEach((res, resIdx) => {
            ctx.fillStyle = `rgba(255, 0, 0, ${0.1 + (resIdx * 0.1)})`; // Distinguish resources
            (res.load || []).forEach(entry => {
                const x = this.dateToX(entry.date);
                const h = (entry.value / 8) * histHeight; // Assume 8h is 100% load
                ctx.fillRect(x, height - h, pixelsPerDay - 2, h);
            });
        });
    }

    drawGrid(ctx, width, height) {
        ctx.strokeStyle = "#e0e0e0";
        ctx.beginPath();
        const pixelsPerDay = this.getPixelsPerDay();
        for (let x = 0; x < width; x += pixelsPerDay) {
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
        }
        ctx.stroke();
    }

    drawBar(ctx, node, index) {
        const x = this.dateToX(node.pln_calc_start);
        const x2 = this.dateToX(node.pln_calc_end);
        const y = index * 40 + 10;
        const w = Math.max(x2 - x, 5);
        const h = 20;

        // Color coding by state
        const stateColors = {
            'history': '#adb5bd',  // Gray
            'wip': '#007bff',      // Blue
            'reserved': '#28a745', // Green
            'tentative': '#ffc107' // Orange
        };
        
        // Find main allocation state if possible
        const state = node.allocations?.[0]?.state || 'reserved';
        ctx.fillStyle = stateColors[state] || "#00A09D";
        
        ctx.fillRect(x, y, w, h);
        
        ctx.fillStyle = "#000";
        ctx.font = "12px sans-serif";
        ctx.fillText(node.name, x + 5, y + 15);
    }

    drawDependencies(ctx) {
        const { nodes } = this.props.model.state;
        ctx.strokeStyle = "rgba(0, 0, 0, 0.3)";
        ctx.lineWidth = 1;

        nodes.forEach((node, index) => {
            const x1 = this.dateToX(node.pln_calc_end);
            const y1 = index * 40 + 20;

            (node.dependencies || []).forEach(targetId => {
                const targetIndex = nodes.findIndex(n => n.id === targetId);
                if (targetIndex === -1) return;

                const targetNode = nodes[targetIndex];
                const x2 = this.dateToX(targetNode.pln_calc_start);
                const y2 = targetIndex * 40 + 20;

                ctx.beginPath();
                ctx.moveTo(x1, y1);
                // Bezier curve for professional look
                const cp1x = x1 + (x2 - x1) / 2;
                const cp2x = x1 + (x2 - x1) / 2;
                ctx.bezierCurveTo(cp1x, y1, cp2x, y2, x2, y2);
                ctx.stroke();
            });
        });
    }

    onMouseDown(ev) {
        const timeline = this.timelineRef.el;
        if (!timeline) return;
        const rect = timeline.getBoundingClientRect();
        const mouseX = ev.clientX - rect.left + timeline.scrollLeft;
        const mouseY = ev.clientY - rect.top + timeline.scrollTop;

        const { nodes } = this.props.model.state;
        const clickedNodeIndex = nodes.findIndex((node, index) => {
            const x = this.dateToX(node.pln_calc_start);
            const x2 = this.dateToX(node.pln_calc_end);
            const y = index * 40 + 10;
            return mouseX >= x && mouseX <= x2 && mouseY >= y && mouseY <= y + 20;
        });

        if (clickedNodeIndex !== -1) {
            this.state.draggingNodeId = nodes[clickedNodeIndex].id;
            this.dragStartX = mouseX;
            this.initialStart = new Date(nodes[clickedNodeIndex].pln_calc_start);
            this.initialEnd = new Date(nodes[clickedNodeIndex].pln_calc_end);
            this.canvasRef.el.style.cursor = "grabbing";
        }
    }

    onMouseMove(ev) {
        if (!this.state.draggingNodeId) return;

        const timeline = this.timelineRef.el;
        if (!timeline) return;
        const rect = timeline.getBoundingClientRect();
        const mouseX = ev.clientX - rect.left + timeline.scrollLeft;
        const dx = mouseX - this.dragStartX;
        const daysShift = dx / this.getPixelsPerDay();

        const node = this.props.model.state.nodes.find(n => n.id === this.state.draggingNodeId);
        if (node) {
            // Optimistic Update
            const newStart = new Date(this.initialStart);
            newStart.setDate(newStart.getDate() + daysShift);
            const newEnd = new Date(this.initialEnd);
            newEnd.setDate(newEnd.getDate() + daysShift);
            
            node.pln_calc_start = newStart;
            node.pln_calc_end = newEnd;
            this.draw();
        }
    }

    onMouseUp(ev) {
        if (this.state.draggingNodeId) {
            const node = this.props.model.state.nodes.find(n => n.id === this.state.draggingNodeId);
            this.props.model.updateTaskDate(node.id, node.pln_calc_start, node.pln_calc_end);
            this.state.draggingNodeId = null;
            this.canvasRef.el.style.cursor = "grab";
        }
    }
}
