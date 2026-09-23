/** @odoo-module **/

import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

/**
 * A standalone list with js_class="poly_list": a row opens its concrete form, and
 * "New" asks for the subtype first.
 */
registry.category("web_tour.tours").add("numa_poly_list_tour", {
    steps: () => [
        {
            content: "Open a Test2 row of the base list",
            trigger: ".o_list_view .o_data_row:contains('Two A1') td[name=a1]",
            run: "click",
        },
        {
            content: "The form is Test2's own: it shows a3",
            trigger: ".o_form_view .o_field_widget[name=a3] input:value(Two A3)",
        },
        {
            content: "Back to the list",
            trigger: ".o_breadcrumb .breadcrumb-item a:contains('Polymorphic items')",
            run: "click",
        },
        {
            content: "New asks for the subtype",
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            trigger: ".modal .o_poly_subtype[data-model='test.test3']",
            run: "click",
        },
        {
            content: "Test3's form, for a new record",
            trigger: ".o_form_view .o_field_widget[name=a4] input",
            run: "edit Listed A4",
        },
        {
            trigger: ".o_form_view .o_field_widget[name=a1] input",
            run: "edit Listed A1",
        },
        ...stepUtils.saveForm(),
    ],
});

/**
 * A one2many with widget="numa_polimorphic_widget": "Add" asks for the subtype, the
 * concrete form fills a virtual line, and saving the parent creates the concrete
 * record. A saved line opens its concrete form.
 */
registry.category("web_tour.tours").add("numa_poly_widget_tour", {
    steps: () => [
        {
            content: "Add a line",
            trigger: ".o_field_widget[name=item_ids] .o_field_x2many_list_row_add button",
            run: "click",
        },
        {
            trigger: ".modal .o_poly_subtype[data-model='test.test3']",
            run: "click",
        },
        {
            content: "Test3's form opens in a dialog",
            trigger: ".modal .o_form_view .o_field_widget[name=a4] input",
            run: "edit New A4",
        },
        {
            trigger: ".modal .o_form_view .o_field_widget[name=a1] input",
            run: "edit New A1",
        },
        {
            trigger: ".modal .o_form_button_save",
            run: "click",
        },
        {
            content: "The line shows what was entered",
            trigger: "body:not(:has(.modal)) .o_field_widget[name=item_ids] .o_data_row:contains('New A1')",
        },
        ...stepUtils.saveForm(),
        {
            content: "Open the line that was already saved",
            trigger: ".o_field_widget[name=item_ids] .o_data_row:contains('Saved A1') td[name=a1]",
            run: "click",
        },
        {
            content: "Its concrete form, Test2's, with a3",
            trigger: ".modal .o_form_view .o_field_widget[name=a3] input:value(Saved A3)",
            run: "edit Edited A3",
        },
        {
            trigger: ".modal .o_form_button_save",
            run: "click",
        },
        {
            trigger: "body:not(:has(.modal))",
        },
    ],
});
