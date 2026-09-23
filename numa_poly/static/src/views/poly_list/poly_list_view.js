/** @odoo-module **/

/**
 * Polymorphic standalone list: `<list js_class="poly_list">` on a polymorphic base.
 *
 * - Opening a row shows the form of the record's concrete model, in the same window
 *   with a breadcrumb, instead of the base model's generic form.
 * - "New" asks which subtype to create, then opens that subtype's form.
 *
 * A model with no subtype behaves exactly like an ordinary list.
 */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { concreteModelOf, pickSubtype } from "../poly_ui";

export class PolyListController extends ListController {
    setup() {
        super.setup();
        this.polyDialog = useService("dialog");
    }

    async openRecord(record, options = {}) {
        const concrete = await concreteModelOf({
            orm: this.orm,
            resModel: record.resModel,
            resId: record.resId,
        });
        if (!concrete) {
            return super.openRecord(record, options);
        }
        return this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                res_model: concrete,
                res_id: record.resId,
                views: [[false, "form"]],
                target: "current",
                context: this.props.context,
            },
            { newWindow: options.newWindow }
        );
    }

    async createRecord(params = {}) {
        const subtype = await pickSubtype({
            orm: this.orm,
            dialog: this.polyDialog,
            resModel: this.props.resModel,
            context: this.props.context,
        });
        if (subtype === undefined) {
            return super.createRecord(params);
        }
        if (!subtype) {
            return; // dismissed
        }
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: subtype.model,
            views: [[false, "form"]],
            target: "current",
            context: this.props.context,
        });
    }
}

export const polyListView = {
    ...listView,
    Controller: PolyListController,
};

registry.category("views").add("poly_list", polyListView);
