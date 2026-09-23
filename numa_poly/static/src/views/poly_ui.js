/** @odoo-module **/

/**
 * Pieces shared by the polymorphic list view (`js_class="poly_list"`) and the
 * polymorphic x2many widget (`widget="numa_polimorphic_widget"`).
 *
 * A polymorphic base model (a root with `_depend_models = {}`, or any model of a
 * hierarchy) has subtypes. Where the base is listed, a row must open its concrete
 * model's form, and creating asks which subtype to create. The server says which
 * subtypes exist (`poly_ui_subclasses`) and what each record really is
 * (`poly_ui_concrete_models`).
 */
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { Component, useProps, t } from "@odoo/owl";

export class PolySubtypeDialog extends Component {
    static template = "numa_poly.PolySubtypeDialog";
    static components = { Dialog };
    props = useProps({
        subtypes: t.array(),
        onPick: t.function(),
        close: t.function(),
    });

    get title() {
        return _t("What do you want to create?");
    }

    pick(subtype) {
        this.props.onPick(subtype);
        this.props.close();
    }
}

/**
 * Ask which subtype to create. Resolves to the chosen `{model, name, model_id}`, or
 * to null when the dialog is dismissed. With a single subtype nothing is asked.
 * Resolves to undefined when the model has no subtype: the caller then does what an
 * ordinary list or one2many would.
 */
export async function pickSubtype({ orm, dialog, resModel, context }) {
    const subtypes = await orm.call(resModel, "poly_ui_subclasses", [], { context });
    if (!subtypes.length) {
        return undefined;
    }
    if (subtypes.length === 1) {
        return subtypes[0];
    }
    return new Promise((resolve) => {
        let picked = null;
        dialog.add(
            PolySubtypeDialog,
            { subtypes, onPick: (subtype) => (picked = subtype) },
            { onClose: () => resolve(picked) }
        );
    });
}

/** The concrete model of a saved record, or null if it is the base itself. */
export async function concreteModelOf({ orm, resModel, resId }) {
    if (!resId) {
        return null;
    }
    const byId = await orm.call(resModel, "poly_ui_concrete_models", [[resId]]);
    const concrete = byId[resId] || byId[String(resId)];
    return concrete && concrete !== resModel ? concrete : null;
}
