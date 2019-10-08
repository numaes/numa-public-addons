# -*- coding: utf-8 -*-

from odoo import models, fields, api, tools
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _get_default_currency(self):
        defaultCompany = self.env.user.company_id
        if defaultCompany:
            return defaultCompany.currency_id.id
        else:
            return False

    price_kind = fields.Selection(
        [
            ('unit', 'Per unit'),
            ('weight', 'Based on weight'),
        ],
        'Price computation',
        default='unit',
    )

    list_price_currency = fields.Many2one('res.currency', 'List price currency',
                                          default=_get_default_currency, required=True)
    cost_currency = fields.Many2one('res.currency', 'Cost currency',
                                    default=_get_default_currency, required=True)

    def _compute_currency_id(self):
        for template in self:
            if template.list_price_currency:
                template.currency_id = template.list_price_currency
            else:
                super(ProductTemplate, template)._compute_currency_id()

    def convert_to_price_kind(self, price):
        self.ensure_one()

        if self.price_kind == 'weight':
            return price * self.weight_net

        return price


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _compute_currency_id(self):
        for product in self:
            product.currency_id = product.product_tmpl_id.company_id.id

    def price_compute(self, price_type, uom=False, currency=False, company=False):
        prices = super(ProductProduct, self).price_compute(price_type,
                                                           uom=uom,
                                                           currency=False,
                                                           company=company)
        if price_type == 'list_price':
            for product in self:
                prices[product.id] = product.list_price_currency.compute(
                    prices[product.id],
                    currency or product.list_price_currency or product.cost_currency
                )
        else:
            for product in self:
                if product.cost_currency:
                    prices[product.id] = product.cost_currency.compute(
                        prices[product.id],
                        currency or product.list_price_currency or product.cost_currency
                    )

        return prices

    def convert_to_price_kind(self, price):
        self.ensure_one()

        if self.price_kind == 'weight':
            return price * self.weight_net

        return price


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    def _compute_price_rule(self, products_qty_partner, date=False, uom_id=False):
        r"""
        Low-level method - Mono pricelist, multi products
        Returns: dict{product_id: (price, suitable_rule) for the given pricelist}

        If date in context: Date of the pricelist (%Y-%m-%d)

            :param products_qty_partner: list of typles products, quantity, partner
            :param datetime date: validity date
            :param ID uom_id: intermediate unit of measure

        """
        self.ensure_one()
        if not date:
            date = self._context.get('date') or fields.Date.context_today(self)
        if not uom_id and self._context.get('uom'):
            uom_id = self._context['uom']
        if uom_id:
            # rebrowse with uom if given
            products = [product.with_context(uom=uom_id) for product, qty, partner in products_qty_partner]
            products_qty_partner = [(products[index], data_struct[1], data_struct[2])
                                    for index, data_struct in enumerate(products_qty_partner)]
        else:
            products = [product for product, qty, partner in products_qty_partner]

        if not products:
            return {}

        pricelist = self.with_context(basePricelistComputation=True)

        items = self.env['product.pricelist.item'].search([
            ('pricelist_id', '=', pricelist.id),
            '|', ('date_start', '=', False), ('date_start', '<=', date),
            '|', ('date_end', '=', False), ('date_end', '>=', date),
        ])

        results = {}
        for product, qty, partner in products_qty_partner:
            results[product.id] = 0.0
            # Final unit price is computed according to `qty` in the `qty_uom_id` UoM.
            # An intermediary unit price may be computed according to a different UoM, in
            # which case the price_uom_id contains that UoM.
            # The final price will be converted to match `qty_uom_id`.

            qty_uom_id = self._context.get('uom') or product.uom_id.id
            qty_in_product_uom = qty
            if qty_uom_id != product.uom_id.id:
                try:
                    qty_in_product_uom = self.env['uom.uom'].browse([self._context['uom']]).\
                        _compute_quantity(qty, product.uom_id)
                except UserError:
                    # Ignored - incompatible UoM in context, use default product UoM
                    pass

            # if Public user try to access standard price from website sale, need to call price_compute.
            # TDE SURPRISE: product can actually be a template
            price_uom = self.env['uom.uom'].browse([qty_uom_id])
            for rule in items:
                if rule.is_appliable(product, qty, partner):
                    price = rule.internal_compute_price(product, qty, partner, price_uom, qty_in_product_uom, date)
                    if price:
                        if 'basePricelistComputation' not in self.env.context:
                            price = product.convert_to_price_kind(price)
                        results[product.id] = (price, rule.id)
                        break

        return results


class PricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    def is_appliable(self, product, qty, partner):
        self.ensure_one()

        rule = self
        is_product_template = product._name == "product.template"

        if rule.min_quantity and qty < rule.min_quantity:
            return False

        if is_product_template:
            if rule.product_tmpl_id and product.id != rule.product_tmpl_id.id:
                return False
            if rule.product_id and not (
                    product.product_variant_count == 1 and product.product_variant_id.id == rule.product_id.id):
                # product rule acceptable on template if has only one variant
                return False
        else:
            if rule.product_tmpl_id and product.product_tmpl_id.id != rule.product_tmpl_id.id:
                return False
            if rule.product_id and product.id != rule.product_id.id:
                return False

        if rule.categ_id:
            cat = product.categ_id
            while cat:
                if cat.id == rule.categ_id.id:
                    break
                cat = cat.parent_id
            if not cat:
                return False

        return True

    def internal_compute_price(self, product, qty, partner, price_uom, qty_in_product_uom, date):
        self.ensure_one()

        rule = self

        if rule.base == 'pricelist' and rule.base_pricelist_id:
            price_tmp = rule.base_pricelist_id._compute_price_rule(
                [(product, qty, partner)]
            )[product.id][0]  # TDE: 0 = price, 1 = rule
            price = rule.base_pricelist_id.currency_id._convert(
                price_tmp,
                rule.pricelist_id.currency_id,
                self.env.user.company_id,
                date,
                round=False
            )
        else:
            # if base option is public price take sale price else cost price of product
            # price_compute returns the price in the context UoM, i.e. qty_uom_id

            price = product.price_compute(rule.base)[product.id]

        convert_to_price_uom = (lambda price: product.uom_id._compute_price(price, price_uom))

        if price:
            if rule.compute_price == 'fixed':
                price = convert_to_price_uom(rule.fixed_price)
            elif rule.compute_price == 'percentage':
                price = (price - (price * (rule.percent_price / 100))) or 0.0
            else:
                # complete formula
                price_limit = price
                price = (price - (price * (rule.price_discount / 100))) or 0.0
                if rule.price_round:
                    price = tools.float_round(price, precision_rounding=rule.price_round)

                if rule.price_surcharge:
                    price_surcharge = convert_to_price_uom(rule.price_surcharge)
                    price += price_surcharge

                if rule.price_min_margin:
                    price_min_margin = convert_to_price_uom(rule.price_min_margin)
                    price = max(price, price_limit + price_min_margin)

                if rule.price_max_margin:
                    price_max_margin = convert_to_price_uom(rule.price_max_margin)
                    price = min(price, price_limit + price_max_margin)

        return price
