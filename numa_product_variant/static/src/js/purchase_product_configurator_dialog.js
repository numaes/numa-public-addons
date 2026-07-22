/** @odoo-module **/

import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";

/**
 * Reuses the Sales product configurator dialog for Purchase Orders.
 * Only the backend endpoints change; all attribute-selection UI is inherited.
 */
export class PurchaseProductConfiguratorDialog extends ProductConfiguratorDialog {
    setup() {
        super.setup();
        this.getValuesUrl = "/purchase/product_configurator/get_values";
        this.createProductUrl = "/purchase/product_configurator/create_product";
        this.updateCombinationUrl = "/purchase/product_configurator/update_combination";
        // getOptionalProductsUrl intentionally unused: no optional products in purchase.
    }
}
