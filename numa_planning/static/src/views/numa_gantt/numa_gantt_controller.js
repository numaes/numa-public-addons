/** @odoo-module **/

import { Controller } from "@web/views/view_controller";
import { useService } from "@web/core/utils/hooks";

export class NumaGanttController extends Controller {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    async onZoomIn() {
        await this.model.changeScale('in');
    }

    async onZoomOut() {
        await this.model.changeScale('out');
    }

    async onAutoSchedule() {
        await this.model.orm.call(this.model.resModel, "pln_action_auto_schedule", [this.model.root_id]);
        await this.model.load();
    }

    async onSimulate() {
        // Placeholder for simulation logic
    }
}
