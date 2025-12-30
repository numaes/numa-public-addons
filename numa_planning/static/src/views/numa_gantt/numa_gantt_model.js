/** @odoo-module **/

import { Model } from "@web/views/model";
import { useService } from "@web/core/utils/hooks";

export class NumaGanttModel extends Model {
    setup(params) {
        this.orm = useService("orm");
        this.resModel = params.resModel;
        this.state = {
            nodes: [],
            resources: [],
            scale: 'day', // 'day', 'week', 'month'
            scrollPosition: { x: 0, y: 0 },
            startDate: new Date(),
            endDate: new Date(),
        };
    }

    async load(params) {
        const ganttData = await this.orm.call(this.resModel, "pln_get_gantt_data", [], {
            domain: params?.domain || [],
        });

        this.state.nodes = ganttData.nodes;
        this.state.resources = ganttData.resources;
        this.state.backlog = ganttData.backlog;
        
        this.computeRange();
        this.notify();
    }

    computeRange() {
        if (this.state.nodes.length === 0) {
            this.state.startDate = new Date();
            this.state.endDate = new Date();
            this.state.endDate.setDate(this.state.endDate.getDate() + 30);
            return;
        }
        let min = new Date(Math.min(...this.state.nodes.map(n => new Date(n.pln_calc_start))));
        let max = new Date(Math.max(...this.state.nodes.map(n => new Date(n.pln_calc_end))));
        
        // Add padding
        min.setDate(min.getDate() - 7);
        max.setDate(max.getDate() + 30);
        
        this.state.startDate = min;
        this.state.endDate = max;
    }

    async changeScale(direction) {
        const scales = ['day', 'week', 'month'];
        let idx = scales.indexOf(this.state.scale);
        if (direction === 'in' && idx > 0) idx--;
        if (direction === 'out' && idx < scales.length - 1) idx++;
        this.state.scale = scales[idx];
        this.notify();
    }

    async updateTaskDate(nodeId, newStart, newEnd) {
        const success = await this.orm.call(this.resModel, "pln_gantt_update_batch", [[{
            id: nodeId,
            start: newStart,
            end: newEnd,
        }]]);
        if (success) {
            await this.load();
        }
    }
}
