from odoo.http import request, route
from odoo.addons.sale.controllers.product_configurator import (
    SaleProductConfiguratorController,
)


class PurchaseProductConfiguratorController(SaleProductConfiguratorController):
    """Reuse the Sales product configurator for Purchase Orders.

    The OWL dialog is reused verbatim (see purchase_product_configurator_dialog.js);
    only the endpoints differ. These routes delegate to the Sales controller but
    neutralize sale pricing: a context flag makes ``_get_basic_product_information``
    return price 0.0, and optional products are dropped. Purchase line pricing is
    recomputed by ``purchase.order.line`` once ``product_id`` is set.
    """

    @route(route='/purchase/product_configurator/get_values',
           type='json', auth='user', methods=['POST'])
    def purchase_product_configurator_get_values(
        self, product_template_id, quantity, currency_id, so_date,
        product_uom_id=None, company_id=None, pricelist_id=None,
        ptav_ids=None, only_main_product=False, **kwargs,
    ):
        """Return configurator values for a purchase line (no sale pricing)."""
        request.update_context(purchase_configurator=True)
        result = self.sale_product_configurator_get_values(
            product_template_id, quantity, currency_id, so_date,
            product_uom_id=product_uom_id, company_id=company_id,
            pricelist_id=None, ptav_ids=ptav_ids,
            only_main_product=True, **kwargs,
        )
        result['optional_products'] = []
        return result

    @route(route='/purchase/product_configurator/update_combination',
           type='json', auth='user', methods=['POST'])
    def purchase_product_configurator_update_combination(
        self, product_template_id, ptav_ids, currency_id, so_date, quantity,
        product_uom_id=None, company_id=None, pricelist_id=None, **kwargs,
    ):
        """Return the updated combination info for a purchase line (no sale pricing)."""
        request.update_context(purchase_configurator=True)
        return self.sale_product_configurator_update_combination(
            product_template_id, ptav_ids, currency_id, so_date, quantity,
            product_uom_id=product_uom_id, company_id=company_id,
            pricelist_id=None, **kwargs,
        )

    @route(route='/purchase/product_configurator/create_product',
           type='json', auth='user', methods=['POST'])
    def purchase_product_configurator_create_product(self, product_template_id, ptav_ids):
        """Create (or reactivate) the variant for a dynamic combination."""
        return self.sale_product_configurator_create_product(product_template_id, ptav_ids)

    def _get_basic_product_information(self, product_or_template, pricelist, combination, **kwargs):
        """In purchase context, skip the sale pricelist and return price 0.0.

        Guarded by the ``purchase_configurator`` context flag so ``/sale/*`` routes
        are unaffected (the derived controller class serves both route families).
        """
        if not request.context.get('purchase_configurator'):
            return super()._get_basic_product_information(
                product_or_template, pricelist, combination, **kwargs)
        basic = dict(**product_or_template.read(['description_sale', 'display_name'])[0])
        if not product_or_template.is_product_variant:
            basic['id'] = False
            combination_name = combination._get_combination_name()
            if combination_name:
                basic['display_name'] = f"{basic['display_name']} ({combination_name})"
        basic['price'] = 0.0
        return basic
