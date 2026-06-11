/** @odoo-module **/

/**
 * Polymorphic top-level List View.
 *
 * Registers the existing PolyListRenderer as a standalone list view (js_class="poly_list"),
 * so a normal action/menu list (e.g. Contacts) navigates to the CONCRETE model's form on
 * open (based on concrete_model_id) and offers subtype selection on create — the same
 * behavior the `numa_polimorphic_widget` x2many field already gives, but for top-level lists.
 *
 * Usage in a list view arch:
 *   <list js_class="poly_list">
 *       <field name="concrete_model_id"/>
 *       ... other columns ...
 *       <field name="poly_payload" column_invisible="1"/>
 *   </list>
 */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { PolyListRenderer } from "./poly_list_renderer";

export const polyListView = {
    ...listView,
    Renderer: PolyListRenderer,
};

registry.category("views").add("poly_list", polyListView);
