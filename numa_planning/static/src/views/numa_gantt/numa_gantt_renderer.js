/** @odoo-module **/

import { Component, useRef, onMounted, onPatched, useState } from "@odoo/owl";

export class NumaGanttRenderer extends Component {
    static template = "numa_planning.NumaGanttRenderer";
    static props = ["model"];

    setup() {
        this.canvasTopRef = useRef("canvas_top");
        this.canvasBottomRef = useRef("canvas_bottom");
        this.treeTopRef = useRef("tree_top");
        this.treeBottomRef = useRef("tree_bottom");
        this.timelineTopRef = useRef("timeline_top");
        this.timelineBottomRef = useRef("timeline_bottom");
        
        this.state = useState({
            hoveredNodeId: null,
            draggingNodeId: null,
            draggingBacklogTask: null,
            showBacklog: false,
            mouseX: 0,
            mouseY: 0,
            activePane: 'top', // 'top' or 'bottom'
        });

        onMounted(() => {
            this.draw();
        });
        onPatched(() => this.draw());
    }

    onScrollTop() {
        const top = this.timelineTopRef.el;
        const bottom = this.timelineBottomRef.el;
        if (top && bottom) {
            bottom.scrollLeft = top.scrollLeft;
        }
        if (this.treeTopRef.el && top) {
            this.treeTopRef.el.scrollTop = top.scrollTop;
        }
    }

    onScrollBottom() {
        const top = this.timelineTopRef.el;
        const bottom = this.timelineBottomRef.el;
        if (top && bottom) {
            top.scrollLeft = bottom.scrollLeft;
        }
        if (this.treeBottomRef.el && bottom) {
            this.treeBottomRef.el.scrollTop = bottom.scrollTop;
        }
    }

    toggleBacklog() {
        this.state.showBacklog = !this.state.showBacklog;
    }

    onBacklogMouseDown(ev, task) {
        this.state.draggingBacklogTask = task;
        this.state.draggingNodeId = null;
        this.canvasTopRef.el.style.cursor = "grabbing";
        
        // Setup global mouse up to handle drop anywhere
        const onGlobalUp = (upEv) => {
            this.onMouseUp(upEv);
            document.removeEventListener("pointerup", onGlobalUp);
        };
        document.addEventListener("pointerup", onGlobalUp);
    }

    dateToX(date) {
        const { startDate } = this.props.model.state;
        const diff = new Date(date) - startDate;
        return (diff / (1000 * 60 * 60 * 24)) * this.getPixelsPerDay();
    }

    xToDate(x) {
        const { startDate } = this.props.model.state;
        const days = x / this.getPixelsPerDay();
        const date = new Date(startDate);
        date.setMilliseconds(date.getMilliseconds() + days * 24 * 60 * 60 * 1000);
        return date;
    }

    draw() {
        this.drawPane('top');
        this.drawPane('bottom');
    }

    drawPane(pane) {
        const canvas = pane === 'top' ? this.canvasTopRef.el : this.canvasBottomRef.el;
        const timeline = pane === 'top' ? this.timelineTopRef.el : this.timelineBottomRef.el;
        if (!canvas || !timeline) return;

        const pixelsPerDay = this.getPixelsPerDay();
        const { startDate, endDate, nodes, resources } = this.props.model.state;
        const days = (endDate - startDate) / (1000 * 60 * 60 * 24);
        
        canvas.width = days * pixelsPerDay;
        const rowCount = pane === 'top' ? nodes.length : resources.length;
        canvas.height = Math.max(rowCount * 40 + 50, timeline.clientHeight);

        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        this.drawGrid(ctx, canvas.width, canvas.height);

        if (pane === 'top') {
            this.drawDependencies(ctx);
            nodes.forEach((node, index) => this.drawBar(ctx, node, index));
        } else {
            resources.forEach((res, index) => this.drawResourceRow(ctx, res, index));
        }
        
        // Draw vertical sync line if hovering or dragging
        if (this.state.hoveredNodeId || this.state.draggingNodeId || this.state.draggingBacklogTask) {
            const nodeId = this.state.draggingNodeId || this.state.draggingBacklogTask?.id || this.state.hoveredNodeId;
            const node = nodes.find(n => n.id === nodeId);
            if (node && node.pln_calc_start) {
                const x = this.dateToX(node.pln_calc_start);
                ctx.setLineDash([5, 5]);
                ctx.strokeStyle = "rgba(0, 160, 157, 0.5)";
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, canvas.height);
                ctx.stroke();
                ctx.setLineDash([]);
            }
        }

        // Tooltip logic (manual for canvas)
        if (pane === 'bottom' && this.state.hoveredNodeId) {
            const resIdx = resources.findIndex(r => r.allocations?.some(a => a.node_id === this.state.hoveredNodeId && a.is_external));
            if (resIdx !== -1) {
                const res = resources[resIdx];
                const alloc = res.allocations.find(a => a.node_id === this.state.hoveredNodeId);
                if (alloc && alloc.is_external) {
                    this.drawTooltip(ctx, `Occupied by Project: ${alloc.node_name}`, this.state.mouseX, (resIdx * 40) + 20);
                }
            }
        }
    }

    drawTooltip(ctx, text, x, y) {
        ctx.font = "12px sans-serif";
        const textWidth = ctx.measureText(text).width;
        ctx.fillStyle = "rgba(0,0,0,0.8)";
        ctx.fillRect(x + 10, y - 25, textWidth + 10, 20);
        ctx.fillStyle = "#fff";
        ctx.fillText(text, x + 15, y - 11);
    }

    drawResourceRow(ctx, resource, index) {
        const y = index * 40;
        const rowHeight = 40;
        const width = ctx.canvas.width;

        // Layer 0: Availability
        (resource.availability || []).forEach(ap => {
            const x = this.dateToX(ap.start);
            const x2 = this.dateToX(ap.end);
            const w = x2 - x;
            if (ap.type === 'maintenance' || ap.efficiency === 0) {
                ctx.fillStyle = "rgba(255, 0, 0, 0.1)";
                ctx.fillRect(x, y, w, rowHeight);
            }
        });

        // Layer 1 & 2: Allocations
        (resource.allocations || []).forEach(alloc => {
            const x = this.dateToX(alloc.start);
            const x2 = this.dateToX(alloc.end);
            const w = Math.max(x2 - x, 5);
            const h = 24;
            const barY = y + 8;

            if (alloc.is_external) {
                // Ghost style: Hatching
                ctx.save();
                ctx.fillStyle = "#f8f9fa";
                ctx.fillRect(x, barY, w, h);
                ctx.strokeStyle = "#dee2e6";
                ctx.lineWidth = 1;
                ctx.beginPath();
                for (let i = -h; i < w; i += 5) {
                    ctx.moveTo(x + i, barY + h);
                    ctx.lineTo(x + i + h, barY);
                }
                ctx.clip(new Path2D(`M ${x} ${barY} h ${w} v ${h} h ${-w} z`));
                ctx.stroke();
                ctx.restore();
                ctx.strokeStyle = "#adb5bd";
                ctx.strokeRect(x, barY, w, h);
            } else {
                const stateColors = {
                    'history': '#adb5bd',
                    'wip': '#007bff',
                    'reserved': '#28a745',
                    'tentative': '#ffc107'
                };
                ctx.fillStyle = stateColors[alloc.state] || "#00A09D";
                ctx.fillRect(x, barY, w, h);
                ctx.strokeStyle = "rgba(0,0,0,0.1)";
                ctx.strokeRect(x, barY, w, h);
                
                if (this.state.hoveredNodeId === alloc.node_id) {
                    ctx.strokeStyle = "#714B67";
                    ctx.lineWidth = 2;
                    ctx.strokeRect(x - 2, barY - 2, w + 4, h + 4);
                }
            }
        });
    }

    onMouseDownTop(ev) {
        const timeline = this.timelineTopRef.el;
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
            this.canvasTopRef.el.style.cursor = "grabbing";
        }
    }

    onMouseMove(ev) {
        const timelineTop = this.timelineTopRef.el;
        const timelineBottom = this.timelineBottomRef.el;
        const rectTop = timelineTop.getBoundingClientRect();
        const rectBottom = timelineBottom.getBoundingClientRect();
        
        let mouseX, mouseY, pane;
        if (ev.clientY < rectBottom.top) {
            mouseX = ev.clientX - rectTop.left + timelineTop.scrollLeft;
            mouseY = ev.clientY - rectTop.top + timelineTop.scrollTop;
            pane = 'top';
        } else {
            mouseX = ev.clientX - rectBottom.left + timelineBottom.scrollLeft;
            mouseY = ev.clientY - rectBottom.top + timelineBottom.scrollTop;
            pane = 'bottom';
        }

        // Hover logic
        const { nodes, resources } = this.props.model.state;
        let newHoverId = null;
        if (pane === 'top') {
            const idx = Math.floor((mouseY - 10) / 40);
            if (nodes[idx]) newHoverId = nodes[idx].id;
        } else {
            const resIdx = Math.floor(mouseY / 40);
            const res = resources[resIdx];
            if (res) {
                const alloc = (res.allocations || []).find(a => {
                    const x = this.dateToX(a.start);
                    const x2 = this.dateToX(a.end);
                    return mouseX >= x && mouseX <= x2;
                });
                if (alloc) newHoverId = alloc.node_id;
            }
        }
        this.state.hoveredNodeId = newHoverId;

        // Drag logic
        if (this.state.draggingNodeId || this.state.draggingBacklogTask) {
            this.draw();
        }
    }

    onMouseUp(ev) {
        const timelineBottom = this.timelineBottomRef.el;
        const rectBottom = timelineBottom.getBoundingClientRect();
        const isInBottom = ev.clientY >= rectBottom.top;
        
        if (this.state.draggingNodeId || this.state.draggingBacklogTask) {
            if (isInBottom) {
                const mouseX = ev.clientX - rectBottom.left + timelineBottom.scrollLeft;
                const mouseY = ev.clientY - rectBottom.top + timelineBottom.scrollTop;
                const resIdx = Math.floor(mouseY / 40);
                const resource = this.props.model.state.resources[resIdx];
                
                if (resource) {
                    const newStart = this.xToDate(mouseX);
                    const nodeId = this.state.draggingNodeId || this.state.draggingBacklogTask.id;
                    const effort = this.state.draggingBacklogTask?.effort || 1.0;
                    const newEnd = new Date(newStart);
                    newEnd.setHours(newEnd.getHours() + effort);
                    
                    this.props.model.orm.call(this.props.model.resModel, "pln_gantt_update_batch", [[{
                        id: nodeId,
                        start: newStart,
                        end: newEnd,
                        resource_id: resource.id
                    }]]);
                    this.props.model.load();
                }
            } else if (this.state.draggingNodeId) {
                // Handle standard move in top pane
                const timelineTop = this.timelineTopRef.el;
                const rectTop = timelineTop.getBoundingClientRect();
                const mouseX = ev.clientX - rectTop.left + timelineTop.scrollLeft;
                const dx = mouseX - this.dragStartX;
                const daysShift = dx / this.getPixelsPerDay();
                
                const node = this.props.model.state.nodes.find(n => n.id === this.state.draggingNodeId);
                const newStart = new Date(this.initialStart);
                newStart.setDate(newStart.getDate() + daysShift);
                const newEnd = new Date(this.initialEnd);
                newEnd.setDate(newEnd.getDate() + daysShift);
                
                this.props.model.updateTaskDate(node.id, newStart, newEnd);
            }
            
            this.state.draggingNodeId = null;
            this.state.draggingBacklogTask = null;
            this.canvasTopRef.el.style.cursor = "grab";
        }
    }
}
