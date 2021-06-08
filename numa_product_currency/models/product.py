from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _get_default_currency(self):
        default_company = self.env.user.company_id
        if default_company:
            return default_company.currency_id.id
        else:
            return False

    currency_id = fields.Many2one(
        'res.currency', 'Currency',
        required=True, readonly=False, compute=None,
        default=_get_default_currency)
    cost_currency_id = fields.Many2one(
        'res.currency', 'Cost Currency',
        required=True, readonly=False, compute=None,
        default=_get_default_currency)

    def price_compute(self, price_type, uom=False, currency=False, company=False):
        prices = super(ProductTemplate, self).price_compute(
            price_type,
            uom=uom,
            currency=False,
            company=company
        )

        if price_type == 'list_price':
            for template in self:
                prices[template.id] = template.currency_id.compute(
                    prices[template.id],
                    currency or template.currency_id or self.env.company.currency_id
                )
        else:
            for template in self:
                if template.cost_currency_id:
                    prices[template.id] = template.cost_currency_id.compute(
                        prices[template.id],
                        currency or template.currency_id or self.env.company.currency_id
                    )

        return prices


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _compute_currency_id(self):
        for product in self:
            product.currency_id = product.product_tmpl_id.currency_id.id

    def price_compute(self, price_type, uom=False, currency=False, company=False):
        prices = super(ProductProduct, self).price_compute(
            price_type,
            uom=uom,
            currency=False,
            company=company
        )

        if price_type == 'list_price':
            for product in self:
                prices[product.id] = product.currency_id.compute(
                    prices[product.id],
                    currency or product.currency_id or self.env.company.currency_id
                )
        else:
            for product in self:
                if product.cost_currency_id:
                    prices[product.id] = product.cost_currency_id.compute(
                        prices[product.id],
                        currency or product.currency_id or self.env.company.currency_id
                    )

        return prices
