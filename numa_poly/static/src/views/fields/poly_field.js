/** @odoo-module **/

/**
 * Polymorphic one2many/many2many: `widget="numa_polimorphic_widget"` on a field whose
 * comodel is a polymorphic base.
 *
 * - "Add" asks which subtype, then opens that subtype's form in a dialog. Nothing is
 *   written yet: the values become a new line of the base model, carrying the subtype
 *   and the values as `poly_payload` (JSON). When the parent is saved, the base
 *   model's create receives that payload and creates the concrete record.
 * - Opening a saved line shows its concrete form in a dialog. That form saves on its
 *   own, and the line is reloaded.
 * - Opening a line that is not saved yet reopens its subtype's form with what was
 *   entered, and saving it updates the payload.
 *
 * The list must declare `poly_payload` (it can be invisible), or the payload has
 * nowhere to travel.
 */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { concreteModelOf, pickSubtype } from "../poly_ui";

export class PolyX2ManyField extends X2ManyField {
    setup() {
        super.setup();
        this.polyOrm = useService("orm");
        this.polyDialog = useService("dialog");
    }

    get polyHasPayloadField() {
        return "poly_payload" in this.list.activeFields;
    }

    async onAdd(params = {}) {
        if (this.isMany2Many || !this.polyHasPayloadField) {
            return super.onAdd(params);
        }
        const subtype = await pickSubtype({
            orm: this.polyOrm,
            dialog: this.polyDialog,
            resModel: this.list.resModel,
            context: this.props.context,
        });
        if (subtype === undefined) {
            return super.onAdd(params);
        }
        if (!subtype) {
            return;
        }
        this._polyOpenSubtypeForm({ subtype, values: {}, line: null });
    }

    async openRecord(record) {
        if (!record.resId) {
            const payload = this._polyReadPayload(record);
            if (payload) {
                const subtype = { model: payload.__model, model_id: payload.concrete_model_id };
                return this._polyOpenSubtypeForm({ subtype, values: payload, line: record });
            }
            return super.openRecord(record);
        }
        const concrete = await concreteModelOf({
            orm: this.polyOrm,
            resModel: record.resModel,
            resId: record.resId,
        });
        if (!concrete) {
            return super.openRecord(record);
        }
        this.polyDialog.add(FormViewDialog, {
            resModel: concrete,
            resId: record.resId,
            context: this.props.context,
            readonly: this.props.readonly,
            title: record.data.display_name || _t("Open"),
            onRecordSaved: async () => {
                await record.load();
            },
        });
    }

    _polyReadPayload(record) {
        try {
            const payload = JSON.parse(record.data.poly_payload || "null");
            return payload && payload.__model ? payload : null;
        } catch {
            return null;
        }
    }

    /**
     * Open the subtype's form without saving it: its values go to a line of the list.
     * `values` prefills the form (as defaults); `line` is the virtual line to update, or
     * null to add one.
     */
    _polyOpenSubtypeForm({ subtype, values, line }) {
        const defaults = {};
        for (const [name, value] of Object.entries(values)) {
            if (!name.startsWith("__") && name !== "concrete_model_id") {
                defaults[`default_${name}`] = value;
            }
        }
        this.polyDialog.add(FormViewDialog, {
            resModel: subtype.model,
            context: { ...this.props.context, ...defaults },
            title: subtype.name || _t("New"),
            onRecordSave: async (formRecord) => {
                if (!(await formRecord.checkValidity({ displayNotification: true }))) {
                    return false;
                }
                const changes = formRecord._getChanges();
                delete changes.id;
                await this._polyWriteLine({ subtype, changes, line });
                return true;
            },
        });
    }

    async _polyWriteLine({ subtype, changes, line }) {
        const payload = { ...changes, concrete_model_id: subtype.model_id, __model: subtype.model };
        const shown = {};
        for (const name of Object.keys(this.list.activeFields)) {
            const field = this.list.fields[name];
            if (name in changes && field && !["one2many", "many2many", "many2one"].includes(field.type)) {
                shown[name] = changes[name];
            }
        }
        const record = line || (await this.list.addNewRecord({ position: "bottom" }));
        await record.update({ ...shown, poly_payload: JSON.stringify(payload) });
    }
}

registry.category("fields").add("numa_polimorphic_widget", {
    ...x2ManyField,
    component: PolyX2ManyField,
});
