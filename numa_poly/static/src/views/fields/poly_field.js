/** @odoo-module **/

import { X2ManyField } from "@web/views/fields/x2many/x2many_field";
import { registry } from "@web/core/registry";
import { PolyListRenderer } from "../poly_list/poly_list_renderer";

/**
 * Polymorphic X2Many Field Component
 * 
 * Extends X2ManyField to use PolyListRenderer for handling
 * polymorphic record creation and navigation.
 */
export class PolyX2ManyField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: PolyListRenderer,
    };
}

// Register the widget
registry.category("fields").add("numa_polimorphic_widget", {
    component: PolyX2ManyField,
    supportedTypes: ["one2many", "many2many"],
});
