
from odoo import fields, models, api, _, tools
from odoo.exceptions import UserError, ValidationError
from itertools import chain

import logging
_logger = logging.getLogger(__name__)


class PricelistTag(models.Model):
    _name = 'product.pricelist.tag'
    _description = 'Pricelist Tag'

    name = fields.Char('Tag name', required=True)
    code = fields.Char('Tag code', help='Used to identify tags in code')


class Pricelist(models.Model):
    _inherit = 'product.pricelist'

    versions = fields.One2many('product.pricelist.version', 'pricelist_id', 'Versions')

    def _compute_price_rule(self, products_qty_partner, date=False, uom_id=False):
        """ Low-level method - Mono pricelist, multi products
        Returns: dict{product_id: (price, suitable_rule) for the given pricelist}

        Date in context can be a date, datetime, ...

            :param products_qty_partner: list of typles products, quantity, partner
            :param datetime date: validity date
            :param ID uom_id: intermediate unit of measure
        """
        version_model = self.env['product.pricelist.version']

        self.ensure_one()

        if not date:
            date = self._context.get('date') or fields.Date.today()
        date = fields.Date.to_date(date)  # boundary conditions differ if we have a datetime

        version = version_model.search(
            [
                ('pricelist_id', '=', self.id),
                ('from_date', '<=', date),
                '|', ('valid_til', '=', False), ('valid_til', '>=', date),
            ],
            order='from_date',
            limit=1,
        )

        if not uom_id and self._context.get('uom'):
            uom_id = self._context['uom']
        if uom_id:
            # rebrowse with uom if given
            products = [item[0].with_context(uom=uom_id) for item in products_qty_partner]
            products_qty_partner = [(products[index], data_struct[1], data_struct[2]) for index, data_struct in enumerate(products_qty_partner)]
        else:
            products = [item[0] for item in products_qty_partner]

        if not products:
            return {}

        if not version:
            return {
                product.id: (0.0, False)
                for product, qty, partner in products_qty_partner
            }

        results = {}
        for product, qty, partner in products_qty_partner:
            results[product.id] = (0.0, False)

            price, suitable_rule = version.items.apply(product, qty, partner)

            results[product.id] = (price, suitable_rule and suitable_rule.id or False)

        return results


class PricelistVersion(models.Model):
    _name = 'product.pricelist.version'
    _description = 'Pricelist Version'
    _order = 'sequence'

    sequence = fields.Integer('Sequence')
    name = fields.Char('Name', required=True)
    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist', required=True)

    from_date = fields.Datetime('Valid from', default='get_default_from_date')
    til_date = fields.Datetime('Valid till')

    items = fields.One2many('product.pricelist.item', 'pricelist_version_id', 'Items')

    def get_default_from_time(self):
        return fields.Date.context_today(self)

    def new_version(self):
        self.ensure_one()

        new_version = self.copy({
            'name': _('New Version'),
            'items': [],
        })

        for item in self.items:
            item.copy({
                'pricelist_id': new_version.id,
            })

        return new_version


class PricelistItems(models.Model):
    _inherit = 'product.pricelist.item'

    version_id = fields.Many2one('product.pricelist.version', 'Version')
    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist',
                                   related='version_id.pricelist_id',
                                   store=True, readonly=True)

    def get_base_price(self, product, qty, partner, date=False, uom=False):
        self.ensure_one()

        rule = self
        price_currency = self.pricelist_id.currency_id
        if rule.base == 'pricelist' and rule.base_pricelist_id:
            prices_per_product = self.base_pricelist_id._compute_price_rule(
                [(product, qty, partner)],
                date=date,
                uom_id=uom.id)
            price = prices_per_product[product.id]
            price_currency = self.base_pricelist_id.currency_id
        else:
            price = product.price_compute(rule.base)[product.id]
            price_currency = product.cost_currency_id if rule.base == 'standard_price' else \
                product.currency_id

        return price, price_currency

    def get_price(self, product, qty, partner, date=False, uom=False):
        self.ensure_one()

        rule = self

        price, price_currency = self.get_base_price(product, qty, partner, date, uom)

        convert_to_price_uom = (lambda price: product.uom_id._compute_price(price, uom))

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

        if price_currency != self.pricelist_id.currency_id:
            price = price_currency._convert(price, self.pricelist_id.currency_id, self.env.company, date, round=False)

        return price

    def apply(self, product, qty, partner):
        category_ids = []
        category = product.category_id
        while category:
            category_ids.append(category.id)
            category = category.parent_id

        if product._name == 'product.template':
            product_template_id = product.id
            product_ids = [v.id for v in product.variant_ids]
            is_product_template = True
        else:
            product_template_id = product.product_tmpl_id.id
            product_ids = [product.id]
            is_product_template = False

        partner_ids = []
        target = partner.id
        while target:
            partner_ids.append(target.id)
            target = target.parent_id

        price = 0.0
        suitable_rule = None

        for rule in self:
            if rule.min_quantity and qty < rule.min_quantity:
                continue
            if rule.product_tmpl_id and rule.product_tmpl_id.id != product_template_id:
                continue
            if rule.product_id and rule.product_id.id not in product_ids:
                continue
            if rule.categ_id and rule.categ_id.id not in category_ids:
                continue
            if rule.partner_id and rule.partner_id.id not in partner_ids:
                continue

            # The rule is triggered, compute the price

            price = rule.get_price(product, qty, partner)
            suitable_rule = rule
            break

        return price, suitable_rule
