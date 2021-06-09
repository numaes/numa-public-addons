import logging
from itertools import chain

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_repr

_logger = logging.getLogger(__name__)


class Pricelist(models.Model):
    _inherit = 'product.pricelist'

    def _compute_price_rule(self, products_qty_partner, date=False, uom_id=False):
        """ Low-level method - Mono pricelist, multi products
        Returns: dict{product_id: (price, suitable_rule) for the given pricelist}

        Date in context can be a date, datetime, ...

            :param products_qty_partner: list of typles products, quantity, partner
            :param datetime date: validity date
            :param ID uom_id: intermediate unit of measure
        """
        self.ensure_one()

        if not date:
            date = self._context.get('date') or fields.Datetime.now()
        if not uom_id and self._context.get('uom'):
            uom_id = self._context['uom']
        if uom_id:
            # rebrowse with uom if given
            products = [item[0].with_context(uom=uom_id) for item in products_qty_partner]
            products_qty_partner = [(products[index], data_struct[1], data_struct[2]) for index, data_struct in
                                    enumerate(products_qty_partner)]
        else:
            products = [item[0] for item in products_qty_partner]

        if not products:
            return {}

        # Prepare analysis parameters
        parameters = []

        for product, quantity, partner in products_qty_partner:
            product = product.with_context(uom=uom_id)
            if product._name == "product.template":
                variants = [p.id for p in
                            list(chain.from_iterable(product.product_variant_ids))]
            else:
                variants = [product.id]
                product = product.product_tmpl_id

            categories = []
            next_category = product.categ_id
            while next_category:
                categories.append(next_category)
                next_category = next_category.parent_id

            parameters.append((
                product,
                variants,
                quantity,
                partner,
                categories,
            ))

        result = {}
        for product, variants, quantity, partner, categories in parameters:
            price = 0.0
            suitable_rule = None
            for rule in self.item_ids.sorted(key=lambda r: r.sequence):
                if rule.check_if_triggered(product, variants, quantity, partner,
                                           categories, date, uom_id):
                    base_price = rule.compute_base(product, variants, quantity, partner,
                                                   categories, date, uom_id)

                    price = rule.apply_formula(base_price, product, variants, quantity,
                                               partner, categories, date, uom_id)

                    if not self.currency_id.is_zero(price):
                        suitable_rule = rule
                        break

            result[product.id] = (price, suitable_rule.id if suitable_rule else False)

        return result


class PricelistItem(models.Model):
    _inherit = 'product.pricelist.item'
    _order = 'sequence'

    sequence = fields.Integer('Sequence')
    name = fields.Char('Name', compute=None,
                       default=_("<not defined>"), help="Explicit rule name for this pricelist line.")
    description = fields.Text(
        'Description', compute='_get_pricelist_item_description_price',
        store=True,
        help="Explicit rule description for this pricelist line."
    )
    price = fields.Char(
        'Price', compute='_get_pricelist_item_description_price',
        store=True,
        help="Explicit rule name for this pricelist line.")

    # To avoid raises for unknown uses of the original update function
    def _get_pricelist_item_name_price(self):
        self._get_pricelist_item_description_price()

    product_tmpl_ids = fields.Many2many(
        'product.template', string='Products', ondelete='cascade', check_company=True,
        help="Specify a template if this rule only applies to one product template. Keep it empty otherwise.")
    product_ids = fields.Many2many(
        'product.product', string='Product Variants', ondelete='cascade', check_company=True,
        help="Specify a set of products if this rule only applies to one of them. Keep it empty otherwise.")
    category_ids = fields.Many2many(
        'product.category', string='Product Categories', ondelete='cascade', check_company=True,
        help="Specify some product categories if this rule only applies to products belonging to this category or "
             "its children categories. Keep it empty otherwise.")
    attribute_value_ids = fields.Many2many(
        'product.attribute.value', string='Product Attribute Values', ondelete='cascade', check_company=True,
        help="Specify some product attribute values if this rule only applies to products having any of them. "
             "Keep it empty otherwise.")

    base = fields.Selection(
        selection_add=[('supplier', "Prefered supplier's cost")],
        help="Base price for computation.\n"
             "Sales Price: The base price will be the Sales Price.\n"
             "Cost Price : The base price will be the cost price.\n"
             "Prefered Supplier's price : The vendor's price.'\n"
             "Other Pricelist : Computation of the base price based on another Pricelist.",
        ondelete={'supplier': 'set default'}
    )

    price_surcharge = fields.Monetary(
        'Price Surcharge',
        help='Specify the fixed amount to add or substract(if negative) to the amount calculated with the discount.')
    price_round = fields.Monetary(
        'Price Rounding',
        help="Sets the price so that it is a multiple of this value.\n"
             "Rounding is applied after the discount and before the surcharge.\n"
             "To have prices that end in 9.99, set rounding 10, surcharge -0.01")

    fixed_price = fields.Monetary('Fixed Price')

    @api.onchange('applied_on', 'category_ids', 'product_tmpl_ids', 'product_ids', 'attribute_value_ids',
                  'compute_price', 'fixed_price',
                  'pricelist_id', 'percent_price', 'price_discount', 'price_surcharge')
    @api.depends('applied_on', 'category_ids', 'product_tmpl_ids', 'product_ids', 'attribute_value_ids',
                 'compute_price', 'fixed_price',
                 'pricelist_id', 'percent_price', 'price_discount', 'price_surcharge')
    def _get_pricelist_item_description_price(self):
        for item in self:
            names = []
            if item.category_ids:
                names.append(_("Categories: %s") % ', '.join(i.display_name for i in item.category_ids))
            if item.product_tmpl_ids:
                names.append(_("Products: %s") % ', '.join(i.display_name for i in item.product_tmpl_ids))
            if item.product_ids:
                names.append(_("Variants: %s") % ', '.join(
                    i.display_name for i in item.product_ids))
            if item.attribute_value_ids:
                names.append(
                    _("Attribute values: %s") %
                    ', '.join(i.display_name for i in item.attribute_value_ids))
            if names:
                item.description = '\n'.join(names) + '\n'
            else:
                item.description = _("All Products")

            price_description = ''
            if item.compute_price == 'fixed':
                decimal_places = self.env['decimal.precision'].precision_get('Product Price')
                if item.currency_id.position == 'after':
                    price_description = "%s %s" % (
                        float_repr(
                            item.fixed_price,
                            decimal_places,
                        ),
                        item.currency_id.symbol,
                    )
                else:
                    price_description = "%s %s" % (
                        item.currency_id.symbol,
                        float_repr(
                            item.fixed_price,
                            decimal_places,
                        ),
                    )
            elif item.compute_price == 'percentage':
                price_description = _("%s %% discount", item.percent_price)
            else:
                # It's a formula
                fields = self.fields_get([])

                selection_name = _('<undefined>')
                for selection_description in fields['base']['selection']:
                    if selection_description[0] == item.base:
                        selection_name = selection_description[1]
                price_description = _('Based on %s') % selection_name
                if item.base == 'pricelist':
                    price_description += ' (%s)' % \
                                         (item.base_pricelist_id.display_name if item.base_pricelist_id else _(
                                             '<undefined>'))

                price_description += ', ' + _("%(percentage)s %% discount and %(price)s surcharge",
                                              percentage=item.price_discount, price=item.price_surcharge)
            item.price = price_description

    def check_if_triggered(self, product, variants, qty, partner, categories, date, uom_id):
        if not self.product_tmpl_ids and all([product != v for v in self.product_ids]):
            return False
        if not self.product_ids and all([all([pv for pv in variants]) for v in self.variant_ids]):
            return False
        if not self.min_quantity and self.min_quantity > qty:
            return False
        if not self.partner_id and all([partner != p for p in self.partner_ids]):
            return False
        if not self.category_ids and all([all([pc != c for pc in categories]) for c in self.category_ids]):
            return False
        if not self.attribute_value_ids and \
                all([all([av != pav.product_attribute_value_id for pav in variants.attribute_value_ids])
                     for av in self.attribute_value_ids]):
            return False

        return True

    def compute_base(self, product, variants, qty, partner, categories, date, uom_id):
        variant = variants[0]
        price = 0.0
        if self.base == 'list_price':
            price = variant.list_price
            source_currency = variant.price_currency_id
        elif self.base == 'standard_price':
            price = variant.standard_price
            source_currency = variant.cost_currency_id
        elif self.base == 'pricelist':
            if not self.base_pricelist_id:
                raise UserError(_('A rule says price should be base on another pricelist, '
                                  'but none is defined (%s)') % self.display_name)

            price = self.base_pricelist_id._compute_price_rule(
                [(variant, qty, partner)], date, uom_id)[variant.id][0]
            source_currency = self.base_pricelist_id.currency_id or \
                              self.base_pricelist_id.company_id.currency_id
        elif self.base == 'supplier':
            if variant.seller_ids:
                price = variant.seller_ids[0].price
                source_currency = variant.seller_ids[0].currency_id
            else:
                price = variant.standard_price
                source_currency = variant.cost_currency_id

        return source_currency._convert(
            price,
            self.pricelist_id.currency_id,
            self.pricelist_id.company_id,
            date,
            round=False
        )

    def apply_formula(self, price, product, variants, qty, partner, categories, date, uom_id):
        qty_uom_id = self._context.get('uom') or product.uom_id.id
        price_uom = self.env['uom.uom'].browse([qty_uom_id])
        return self._compute_price(price, price_uom, product, quantity=qty, partner=partner)
