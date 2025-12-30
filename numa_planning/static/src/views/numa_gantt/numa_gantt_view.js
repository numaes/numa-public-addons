/** @odoo-module **/

import { registry } from "@web/core/registry";
import { NumaGanttController } from "./numa_gantt_controller";
import { NumaGanttModel } from "./numa_gantt_model";
import { NumaGanttRenderer } from "./numa_gantt_renderer";
import { NumaGanttArchParser } from "./numa_gantt_arch_parser";

export const numaGanttView = {
    type: "numa_gantt",
    display_name: "Numa Gantt",
    icon: "fa-tasks",
    multi_edit: false,
    Controller: NumaGanttController,
    Model: NumaGanttModel,
    Renderer: NumaGanttRenderer,
    ArchParser: NumaGanttArchParser,

    props(genericProps, view) {
        return {
            ...genericProps,
            Model: view.Model,
            Renderer: view.Renderer,
        };
    },
};

registry.category("views").add("numa_gantt", numaGanttView);
