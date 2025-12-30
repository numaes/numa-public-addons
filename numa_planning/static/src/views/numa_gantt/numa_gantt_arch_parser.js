/** @odoo-module **/

import { XMLParser } from "@web/core/utils/xml";

export class NumaGanttArchParser extends XMLParser {
    parse(arch) {
        const archInfo = {
            dateStartField: "pln_calc_start",
            dateStopField: "pln_calc_end",
        };
        this.visit(arch, (node) => {
            if (node.tagName === "numa_gantt") {
                archInfo.dateStartField = node.getAttribute("date_start") || archInfo.dateStartField;
                archInfo.dateStopField = node.getAttribute("date_stop") || archInfo.dateStopField;
            }
        });
        return archInfo;
    }
}
