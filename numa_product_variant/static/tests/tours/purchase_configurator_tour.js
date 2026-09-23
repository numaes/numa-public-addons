/** @odoo-module **/

import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

/**
 * Picking a configurable template on a purchase order line opens the configurator.
 *
 * The trigger is an effect in PurchaseOrderLineProductField. OWL 3 changed what
 * `useEffect` means (a reactive effect, no dependency list), so the OWL 2 effect is
 * kept through the compatibility layer's useLayoutEffect. Nothing else exercised the
 * purchase side of the configurator in a browser.
 */
registry.category("web_tour.tours").add("numa_purchase_configurator_tour", {
    steps: () => [
        {
            content: "Pick the vendor",
            trigger: ".o_field_widget[name=partner_id] input",
            run: "edit NUMA Tour Vendor",
        },
        {
            trigger: ".o-autocomplete--dropdown-item:contains('NUMA Tour Vendor')",
            run: "click",
        },
        {
            content: "Add a line",
            trigger: ".o_field_x2many_list_row_add button:contains('Add a product')",
            run: "click",
        },
        {
            content: "Type the configurable template",
            trigger: ".o_data_row .o_field_widget[name=product_template_id] input",
            run: "edit NUMA Profile L 40x40",
        },
        {
            trigger: ".o-autocomplete--dropdown-item:contains('NUMA Profile L 40x40')",
            run: "click",
        },
        {
            content: "The configurator opens for the template",
            trigger: ".modal .o_sale_product_configurator_dialog:contains('NUMA Profile L 40x40')",
        },
        {
            content: "Confirm the configuration",
            trigger: ".modal .o_sale_product_configurator_dialog button:contains('Confirm')",
            run: "click",
        },
        ...stepUtils.saveForm(),
        {
            content: "The line carries the configured product, and it was saved",
            trigger: ".o_data_row:contains('NUMA Profile L 40x40')",
        },
    ],
});
