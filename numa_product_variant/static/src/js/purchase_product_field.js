/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { serializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    ProductLabelSectionAndNoteField,
    productLabelSectionAndNoteField,
} from "@account/components/product_label_section_and_note_field/product_label_section_and_note_field";
import { PurchaseProductConfiguratorDialog } from "./purchase_product_configurator_dialog";

/**
 * Purchase order line product field. Mirrors Sales' sol_product_many2one but
 * scoped to variant selection/creation: when the user picks a product template
 * it either auto-assigns the single variant (non-configurable) or opens the
 * purchase configurator dialog, then writes product_id + product_qty on the line.
 */
export class PurchaseOrderLineProductField extends ProductLabelSectionAndNoteField {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.orm = useService("orm");

        let isMounted = false;
        let isInternalUpdate = false;
        const { updateRecord } = this;
        this.updateRecord = (value) => {
            isInternalUpdate = true;
            return updateRecord.call(this, value);
        };
        // React only to user-driven template changes (not onchange/dialog writes),
        // mirroring the trigger mechanism in sale_product_field.js.
        useEffect(
            (value) => {
                if (!isMounted) {
                    isMounted = true;
                } else if (value && isInternalUpdate) {
                    if (this.relation === "product.template") {
                        this._onProductTemplateUpdate();
                    }
                }
                isInternalUpdate = false;
            },
            () => [Array.isArray(this.value) && this.value[0]]
        );
    }

    async _onProductTemplateUpdate() {
        const record = this.props.record;
        const templateId = record.data.product_template_id?.[0];
        if (!templateId) {
            return;
        }
        const result = await this.orm.call(
            "product.template",
            "get_single_product_variant",
            [templateId]
        );
        if (result && result.product_id) {
            if (record.data.product_id?.[0] !== result.product_id) {
                await record.update({
                    product_id: [result.product_id, result.product_name],
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
            productTemplateId: record.data.product_template_id[0],
            ptavIds: [],
            customPtavs: [],
            quantity: record.data.product_qty || 1,
            productUOMId: record.data.product_uom?.[0],
            companyId: orderRecord.data.company_id?.[0],
            currencyId: orderRecord.data.currency_id?.[0],
            soDate: serializeDateTime(orderRecord.data.date_order),
            options: { showPrice: false, showQuantity: true },
            save: async (mainProduct) => {
                await record.update({
                    product_id: [mainProduct.id, mainProduct.display_name],
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
    ...productLabelSectionAndNoteField,
    component: PurchaseOrderLineProductField,
};

registry.category("fields").add("pol_product_many2one", purchaseOrderLineProductField);
