/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { useSubEnv } from "@odoo/owl";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";
import { ProductTemplateAttributeLine } from "@sale/js/product_template_attribute_line/product_template_attribute_line";

/**
 * Open attribute values in the product configurator.
 *
 * An attribute whose values are not confined to a predefined list — a
 * reference to a record, a free number, a free text or a free date — gets an
 * extra control *beside* the list, never instead of it, so a set of
 * suggestions and free entry can coexist. That is the behaviour SAP calls
 * "additional values" and D365 models as "Text with or without a fixed list".
 *
 * The server materialises the value and hands back a template attribute value
 * id, which is the only currency the rest of the configurator understands, so
 * combination update, exclusions, pricing and variant creation are untouched.
 */

patch(ProductConfiguratorDialog.prototype, {
    setup() {
        super.setup();
        // Default endpoint. PurchaseProductConfiguratorDialog overrides this
        // after calling super.setup(), which is why the env exposes a function
        // reading the property lazily rather than the URL itself.
        this.resolveValueUrl = "/sale/product_configurator/resolve_value";
        useSubEnv({
            resolveOpenValue: (params) => rpc(this.resolveValueUrl, params),
            registerOpenValue: (productTmplId, ptavId) =>
                this._registerOpenValue(productTmplId, ptavId),
        });
    },

    /**
     * Make a newly materialised value known to the dialog's exclusion map.
     *
     * The map was built by get_values before this value existed, and core
     * indexes it without a fallback — `exclusions[ptavId]` on a value it has
     * never seen throws. A value created just now excludes nothing, so an
     * empty list is the truthful entry.
     */
    _registerOpenValue(productTmplId, ptavId) {
        const product = this.state.products.find(
            (candidate) => candidate.product_tmpl_id === productTmplId
        );
        if (!product) {
            return;
        }
        product.exclusions ??= {};
        product.exclusions[ptavId] ??= [];
    },
});

patch(ProductTemplateAttributeLine, {
    components: {
        ...ProductTemplateAttributeLine.components,
        Many2XAutocomplete,
    },
});

patch(ProductTemplateAttributeLine.prototype, {

    /**
     * Whether this line accepts a value outside its predefined list.
     *
     * True when the attribute explicitly allows additional values, and also
     * when the list is empty — an open attribute legitimately starts with no
     * predefined values at all.
     */
    get acceptsOpenValue() {
        const attribute = this.props.attribute;
        if (!attribute.value_type) {
            return false; // attribute predates this feature
        }
        return Boolean(attribute.allow_additional_values)
            || this.props.attribute_values.length === 0;
    },

    get openValueType() {
        return this.props.attribute.value_type;
    },

    /** Pick an existing record only: creating one from here is out of scope. */
    get openReferenceActions() {
        return { create: false, createEdit: false, write: false };
    },

    get openReferenceDomain() {
        try {
            return JSON.parse(this.props.attribute.reference_domain || "[]");
        } catch {
            return [];
        }
    },

    /**
     * Materialise the typed value server-side, then select the resulting PTAV.
     */
    async submitOpenValue(payload) {
        const result = await this.env.resolveOpenValue({
            product_template_id: this.props.productTmplId,
            ptal_id: this.props.id,
            payload: payload,
        });
        if (!this.props.attribute_values.some((ptav) => ptav.id === result.ptav_id)) {
            this.props.attribute_values.push({
                id: result.ptav_id,
                name: result.name,
                html_color: false,
                image: false,
                is_custom: false,
                price_extra: 0,
            });
        }
        // Must happen before selecting it: the selection recomputes exclusions,
        // and this value is not in the map the server sent when the dialog
        // loaded.
        this.env.registerOpenValue(this.props.productTmplId, result.ptav_id);
        this.env.updateProductTemplateSelectedPTAV(
            this.props.productTmplId, this.props.id, result.ptav_id, false
        );
    },

    onOpenReferenceSelected(records) {
        if (!records || !records.length) {
            return;
        }
        return this.submitOpenValue({
            reference: [this.props.attribute.reference_model, records[0].id],
        });
    },

    onOpenNumberConfirmed(event) {
        const value = parseFloat(event.target.value);
        if (Number.isNaN(value)) {
            return;
        }
        return this.submitOpenValue({ number: value });
    },

    onOpenTextConfirmed(event) {
        const value = event.target.value.trim();
        if (!value) {
            return;
        }
        return this.submitOpenValue({ char: value });
    },

    onOpenDateConfirmed(event) {
        if (!event.target.value) {
            return;
        }
        return this.submitOpenValue({ date: event.target.value });
    },
});

// The props shape is validated against a closed list, so the new metadata sent
// by _get_product_information has to be declared. They stay optional: an
// attribute created before this feature sends none of them.
Object.assign(ProductTemplateAttributeLine.props.attribute.shape, {
    value_type: { type: String, optional: true },
    allow_additional_values: { type: Boolean, optional: true },
    reference_model: { type: [Boolean, String], optional: true },
    reference_domain: { type: [Boolean, String], optional: true },
    number_min: { type: Number, optional: true },
    number_max: { type: Number, optional: true },
    number_rounding: { type: Number, optional: true },
});
