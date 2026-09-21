/** @odoo-module **/

import { registry } from "@web/core/registry";
// [20.0] `@web_tour/tour_service/tour_utils` moved to `@web_tour/tour_utils`, and
// `@sale/js/tours/tour_utils` exports named functions rather than a default object.
// Both imports failed, so the tour was never registered and the test timed out waiting
// for a tour that did not exist.
import { stepUtils } from "@web_tour/tour_utils";
import { addProduct, createNewSalesOrder, selectCustomer } from "@sale/js/tours/tour_utils";

/**
 * Drives the open-value controls in the real product configurator.
 *
 * The whole open-value feature lives in the browser: the server side is covered
 * by unit tests, but nothing until now proved that the control renders, accepts
 * input and produces a variant. This tour is that proof.
 */
const ptalWithLabel = (name) =>
    `div[name="ptal"]:has(label:contains("${name}"))`;

registry.category("web_tour.tours").add("numa_open_value_configurator_tour", {
    url: "/odoo",
    steps: () => [
        ...stepUtils.goToAppSteps("sale.sale_menu_root", "Go to the Sales App"),
        ...createNewSalesOrder(),
        ...selectCustomer("NUMA Tour Customer"),
        ...addProduct("NUMA Cut piece"),
        {
            content: "The open attribute must be labelled, not a bare input",
            trigger: `.modal ${ptalWithLabel("NUMA Segment length")} .o_ptal_open_value input[type="number"]`,
        },
        {
            content: "Type a segment length nobody predefined",
            trigger: `.modal ${ptalWithLabel("NUMA Segment length")} .o_ptal_open_value input[type="number"]`,
            run: "edit 1250 && click body",
        },
        {
            // Asserted on the product name rather than the input: the typed
            // number lives in a value attribute, and this proves the whole
            // chain — the value was materialised and its code composed into
            // the variant's default_code.
            content: "The value is materialised and reaches the variant code",
            trigger: '.o_sale_product_configurator_dialog:contains("NCUT.CRL1250")',
        },
        {
            content: "Pick the base profile through the reference control",
            trigger: `.modal ${ptalWithLabel("NUMA Profile type")} .o_ptal_open_value input`,
            run: "edit NUMA Profile",
        },
        {
            content: "Choose it from the autocomplete",
            trigger: ".o-autocomplete--dropdown-item:contains('NUMA Profile L 40x40')",
            run: "click",
        },
        {
            content: "The referenced profile reaches the variant code too",
            trigger: '.o_sale_product_configurator_dialog:contains("PNPL4040")',
        },
        {
            content: "Confirm the configuration",
            trigger: '.o_sale_product_configurator_dialog button:contains("Confirm")',
            run: "click",
        },
        // [20.0] Confirming leaves the new line in edit mode, so the product sits in
        // a `textarea.o_input` -- its value, not the cell's text -- and
        // `.o_data_row:contains(...)` waited ten seconds for text that was never
        // there. Saving first closes the row AND proves the line persisted, which is
        // the stronger assertion anyway: what the configurator produced survives a
        // round trip to the server.
        ...stepUtils.saveForm(),
        {
            content: "The line carries the configured variant, and it was saved",
            trigger: '.o_data_row:contains("NUMA Cut piece")',
        },
        {
            content: "And it carries the code the open values composed",
            trigger: '.o_data_row:contains("NCUT.CRL1250")',
        },
    ],
});
