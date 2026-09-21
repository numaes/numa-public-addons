import { t, useEffect, useProps } from "@odoo/owl";
import {
    accountProductField,
    AccountProductField,
} from "@account/components/account_product_field/account_product_field";
import { registry } from "@web/core/registry";
import { serializeDateTime } from "@web/core/l10n/dates";
import { useService } from "@web/core/utils/hooks";
import { many2OneFieldProps } from "@web/views/fields/many2one/many2one_field";
import { PurchaseProductConfiguratorDialog } from "./purchase_product_configurator_dialog";

/**
 * Purchase order line product field. Mirrors Sales' sol_product_many2one but scoped to
 * variant selection and creation: when the user picks a product template it either
 * assigns the single variant, or opens the purchase configurator, and then writes
 * product_id and the quantity on the line.
 *
 * [20.0] Rebuilt on `AccountProductField`. It used to extend
 * `ProductLabelSectionAndNoteField` from `@account/components/...`, which no longer
 * exists -- the module could not even be loaded, and it took
 * `@numa_product_variant/js/purchase_product_field` down with it as a browser console
 * error that nothing in the server log mentioned.
 *
 * Three smaller things moved with it: props are declared with `useProps` rather than a
 * static shape; a many2one value is an object with `id` and `display_name` rather than a
 * pair; and a user-driven change is caught by wrapping `m2oProps.update` rather than
 * `updateRecord`, which is how core tells its own writes apart from the user's.
 */
export class PurchaseOrderLineProductField extends AccountProductField {
    static template = "account.AccountProductField";
    props = useProps({
        ...many2OneFieldProps,
        readonlyField: t.boolean().optional(),
    });

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.isInternalUpdate = false;
        let isMounted = false;

        useEffect(() => {
            const value = this.value && this.value.id;
            if (!isMounted) {
                isMounted = true;
            } else if (value && this.isInternalUpdate && this.relation === "product.template") {
                this._onProductTemplateUpdate();
            }
            this.isInternalUpdate = false;
        });
    }

    get relation() {
        return this.props.record.fields[this.props.name].relation;
    }

    get m2oProps() {
        const props = super.m2oProps;
        return {
            ...props,
            update: (value) => {
                // Only a change the user made opens the configurator. An onchange, or the
                // dialog writing back its own result, must not reopen it.
                this.isInternalUpdate = true;
                return props.update(value);
            },
        };
    }

    async _onProductTemplateUpdate() {
        const record = this.props.record;
        const templateId = record.data.product_template_id?.id;
        if (!templateId) {
            return;
        }
        const result = await this.orm.call(
            "product.template",
            "get_single_product_variant",
            [templateId]
        );
        if (result && result.product_id) {
            if (record.data.product_id?.id !== result.product_id) {
                await record.update({
                    product_id: { id: result.product_id, display_name: result.product_name },
                });
            }
        } else {
            this._openProductConfigurator();
        }
    }

    _openProductConfigurator() {
        const record = this.props.record;
        const orderRecord = record.model.root;
        this.dialog.add(PurchaseProductConfiguratorDialog, {
            productTemplateId: record.data.product_template_id.id,
            ptavIds: [],
            customPtavs: [],
            quantity: record.data.product_qty || 1,
            // [20.0] `purchase.order.line.product_uom` became `uom_id`.
            productUOMId: record.data.uom_id?.id,
            companyId: orderRecord.data.company_id?.id,
            currencyId: orderRecord.data.currency_id?.id,
            soDate: serializeDateTime(orderRecord.data.date_order),
            options: { showPrice: false, showQuantity: true },
            save: async (mainProduct) => {
                await record.update({
                    product_id: { id: mainProduct.id, display_name: mainProduct.display_name },
                    product_qty: mainProduct.quantity,
                });
            },
            discard: () => {
                record.update({ product_template_id: false });
            },
        });
    }

    get isConfigurableTemplate() {
        return this.props.record.data.is_configurable_product;
    }
}

export const purchaseOrderLineProductField = {
    ...accountProductField,
    component: PurchaseOrderLineProductField,
};

registry.category("fields").add("pol_product_many2one", purchaseOrderLineProductField);
