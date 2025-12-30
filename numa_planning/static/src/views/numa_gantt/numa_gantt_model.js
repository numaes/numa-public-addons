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
        const data = await this.orm.call(this.resModel, "search_read", [], {
            domain: params?.domain || [],
            fields: ['id', 'display_name', 'pln_calc_start', 'pln_calc_end'],
        });

        const ganttData = await Promise.all(data.map(node => 
            this.orm.call(this.resModel, "pln_get_gantt_data", [node.id])
        ));

        this.state.nodes = ganttData;
        this.computeRange();

        // Fetch real resource load data for the histogram
        if (this.state.startDate && this.state.endDate) {
            // Format dates to string for Odoo call (YYYY-MM-DD HH:MM:SS)
            const format = (d) => d.toISOString().replace('T', ' ').split('.')[0];
            const startStr = format(this.state.startDate);
            const endStr = format(this.state.endDate);
            
            this.state.resources = await this.orm.call(
                this.resModel, 
                "pln_get_resource_load_data", 
                [startStr, endStr]
            );
        }

        this.notify();
    }

    computeRange() {
        if (this.state.nodes.length === 0) return;
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
