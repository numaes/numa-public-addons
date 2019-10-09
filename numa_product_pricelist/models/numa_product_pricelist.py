##############################################################################
#    
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.     
#
##############################################################################


from odoo import fields, models, api, _, tools
from odoo.exceptions import UserError, ValidationError

from itertools import chain


class numa_product_pricelist(models.Model):
    _inherit = 'product.pricelist'

    description = fields.Char(string='Description')
    pricelist_selection = fields.Boolean(string='Selectable', default="True")
    for_sale = fields.Boolean(u'Use in sales?', default=True)
    for_purchase = fields.Boolean(u'Use in purchases?')
    tipo_cambio = fields.Float(string='Tipo de cambio')
    pricelist_type = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase'), ('reference', 'Reference')],
                                      string='Price List Type', required=True, default='sale')
    pricelist_customer_ids = fields.One2many(comodel_name='res.partner', inverse_name='property_product_pricelist',
                                             string='Partners Customers')
    pricelist_supplier_ids = fields.One2many(comodel_name='res.partner', inverse_name='supplier_pricelist_id',
                                             string='Partners Supplier')
    profile_partner_ids = fields.Many2many(comodel_name='numa.profile_partner_pricelist',
                                           relation='numa_profile_partner_pricelist_rel',
                                           column1='product_pricelist_id', column2='profile_id',
                                           string='Profile Price List')
    acuerdos_count = fields.Integer('# Acuerdos', compute='_compute_acuerdos_count')
    note = fields.Text(string='Note')

    @api.multi
    def action_pricelist_items(self):
        self.ensure_one()

        return {
            'name': _("Acuerdos"),
            'view_mode': 'tree,form',
            'view_type': 'form',
            'res_model': 'product.pricelist.item',
            'res_id': False,
            'type': 'ir.actions.act_window',
            'target': 'current',
            'domain': [('pricelist_id', '=', self.id)],
            'context': {'default_pricelist_id': self.id},
            'nodestroy': False,
        }

    def _compute_acuerdos_count(self):
        read_group_res = self.env['product.pricelist.item'].read_group([('pricelist_id', 'in', self.ids)],
                                                                       ['pricelist_id'], ['pricelist_id'])
        mapped_data = dict([(data['pricelist_id'][0], data['pricelist_id_count']) for data in read_group_res])
        for pricelist in self:
            pricelist.acuerdos_count = mapped_data.get(pricelist.id, 0)

    @api.multi
    def _compute_price_rule(self, products_qty_partner, date=False, uom_id=False):
        ctx = self.env.context

        lot_id = ctx.get('lot_id', False)
        serial_id = ctx.get('serial_id', False)
        afip_punto_venta_id = ctx.get('afip_punto_venta_id', False)
        salesman_id = ctx.get('salesman_id', False)
        city_id = ctx.get('city_id', False)
        country_state_id = ctx.get('country_state_id', False)
        country_id = ctx.get('country_id', False)

        """ Low-level method - Mono pricelist, multi products
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
            products = [item[0].with_context(uom=uom_id) for item in products_qty_partner]
            products_qty_partner = [(products[index], data_struct[1], data_struct[2]) for index, data_struct in
                                    enumerate(products_qty_partner)]
        else:
            products = [item[0] for item in products_qty_partner]

        if not products:
            return {}

        categ_ids = {}
        for p in products:
            categ = p.categ_id
            while categ:
                categ_ids[categ.id] = True
                categ = categ.parent_id
        categ_ids = categ_ids.keys()

        is_product_template = products[0]._name == "product.template"
        if is_product_template:
            prod_tmpl_ids = [tmpl.id for tmpl in products]
            # all variants of all products
            prod_ids = [p.id for p in
                        list(chain.from_iterable([t.product_variant_ids for t in products]))]
        else:
            prod_ids = [product.id for product in products]
            prod_tmpl_ids = [product.product_tmpl_id.id for product in products]

        # Load all rules
        self._cr.execute(
            'SELECT item.id '
            'FROM product_pricelist_item AS item '
            'LEFT JOIN product_category AS categ '
            'ON item.categ_id = categ.id '
            'WHERE (item.product_tmpl_id IS NULL OR item.product_tmpl_id = any(%s))'
            'AND (item.product_id IS NULL OR item.product_id = any(%s))'
            'AND (item.categ_id IS NULL OR item.categ_id = any(%s)) '
            'AND (item.pricelist_id = %s) '
            'AND (item.date_start IS NULL OR item.date_start<=%s) '
            'AND (item.date_end IS NULL OR item.date_end>=%s)'
            'ORDER BY item.sequence',
            (prod_tmpl_ids, prod_ids, categ_ids, self.id, date, date))

        item_ids = [x[0] for x in self._cr.fetchall()]
        items = self.env['product.pricelist.item'].browse(item_ids)
        results = {}
        for product, qty, partner in products_qty_partner:
            results[product.id] = 0.0
            suitable_rule = False

            # Final unit price is computed according to `qty` in the `qty_uom_id` UoM.
            # An intermediary unit price may be computed according to a different UoM, in
            # which case the price_uom_id contains that UoM.
            # The final price will be converted to match `qty_uom_id`.
            qty_uom_id = self._context.get('uom') or product.uom_id.id
            price_uom_id = product.uom_id.id
            qty_in_product_uom = qty
            if qty_uom_id != product.uom_id.id:
                try:
                    qty_in_product_uom = self.env['product.uom'].browse([self._context['uom']])._compute_quantity(qty,
                                                                                                                  product.uom_id)
                except UserError:
                    # Ignored - incompatible UoM in context, use default product UoM
                    pass

            # if Public user try to access standard price from website sale, need to call price_compute.
            # TDE SURPRISE: product can actually be a template
            price = 0.0  # product.price_compute('list_price')[product.id]

            price_uom = self.env['product.uom'].browse([qty_uom_id])
            for rule in items:
                if rule.min_quantity and qty_in_product_uom < rule.min_quantity:
                    continue

                if rule.max_quantity and qty_in_product_uom > rule.max_quantity:
                    continue

                if rule.applied_on == '4_multi':
                    if not rule.not_multiple_condition:
                        if rule.product_tmpl_ids and \
                                product.product_tmpl_id.id not in rule.product_tmpl_ids.ids:
                            continue
                        if rule.product_ids and \
                                product.id not in rule.product_ids.ids:
                            continue
                        if rule.product_category_ids and \
                                product.categ_id.id not in rule.product_category_ids.ids:
                            continue
                        if rule.product_trademark_ids and \
                                product.product_trademark_id.id not in rule.product_trademark_ids:
                            continue
                        if rule.product_lot_ids and lot_id and \
                                lot_id not in rule.product_lot_ids.ids:
                            continue
                        if rule.product_serial_ids and serial_id and \
                                serial_id not in rule.product_serial_ids.ids:
                            continue
                        if rule.partner_category_ids and partner and partner.category_id and \
                                partner.category_id.id not in rule.partner_category_ids:
                            continue
                        if rule.afip_punto_venta_ids and afip_punto_venta_id and \
                                afip_punto_venta_id not in rule.afip_punto_venta_ids:
                            continue
                        if rule.partner_seller_ids and salesman_id and \
                                salesman_id not in rule.partner_seller_ids.ids:
                            continue
                        if rule.city_ids and city_id and \
                                city_id not in rule.city_ids.ids:
                            continue
                        if rule.state_ids and country_state_id and \
                                country_state_id not in rule.state_ids.ids:
                            continue
                        if rule.country_ids and country_id and \
                                country_id not in rule.country_ids.ids:
                            continue
                    else:
                        if rule.product_tmpl_ids and \
                                product.product_tmpl_id.id in rule.product_tmpl_ids.ids:
                            continue
                        if rule.product_ids and \
                                product.id in rule.product_ids.ids:
                            continue
                        if rule.product_category_ids and \
                                product.categ_id.id in rule.product_category_ids.ids:
                            continue
                        if rule.product_trademark_ids and \
                                product.product_trademark_id.id in rule.product_trademark_ids.ids:
                            continue
                        if rule.product_lot_ids and lot_id and \
                                lot_id in rule.product_lot_ids.ids:
                            continue
                        if rule.product_serial_ids and serial_id and \
                                serial_id in rule.product_serial_ids.ids:
                            continue
                        if rule.partner_category_ids and partner and partner.category_id and \
                                set(partner.category_id.ids) in set(rule.partner_category_ids.ids):
                            continue
                        if rule.afip_punto_venta_ids and afip_punto_venta_id and \
                                afip_punto_venta_id in rule.afip_punto_venta_ids:
                            continue
                        if rule.partner_seller_ids and salesman_id and \
                                salesman_id in rule.partner_seller_ids.ids:
                            continue
                        if rule.city_ids and city_id and \
                                city_id in rule.city_ids.ids:
                            continue
                        if rule.state_ids and country_state_id and \
                                country_state_id in rule.state_ids.ids:
                            continue
                        if rule.country_ids and country_id and \
                                country_id in rule.country_ids.ids:
                            continue

                if is_product_template:
                    if rule.product_tmpl_id and product.id != rule.product_tmpl_id.id:
                        continue
                    if rule.product_id and not (
                            product.product_variant_count == 1 and product.product_variant_id.id == rule.product_id.id):
                        # product rule acceptable on template if has only one variant
                        continue
                else:
                    if rule.product_tmpl_id and product.product_tmpl_id.id != rule.product_tmpl_id.id:
                        continue
                    if rule.product_id and product.id != rule.product_id.id:
                        continue

                if rule.categ_id:
                    cat = product.categ_id
                    while cat:
                        if cat.id == rule.categ_id.id:
                            break
                        cat = cat.parent_id
                    if not cat:
                        continue

                if rule.base == 'pricelist' and rule.base_pricelist_id:
                    price_tmp = rule.base_pricelist_id._compute_price_rule([(product, qty, partner)])[product.id][
                        0]  # TDE: 0 = price, 1 = rule
                    price = rule.base_pricelist_id.currency_id.compute(price_tmp, self.currency_id, round=False)
                else:
                    # if base option is public price take sale price else cost price of product
                    # price_compute returns the price in the context UoM, i.e. qty_uom_id
                    price = product.with_context(currency=self.currency_id.id).price_compute(rule.base)[product.id]

                convert_to_price_uom = (lambda price: product.uom_id._compute_price(price, price_uom))

                if price is not False:
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
                    suitable_rule = rule
                break
            # Final price conversion into pricelist currency
            #if suitable_rule and suitable_rule.compute_price != 'fixed' and suitable_rule.base != 'pricelist':
            #    price = product.currency_id.compute(price, self.currency_id, round=False)

            results[product.id] = (price, suitable_rule and suitable_rule.id or False)

        return results


class numa_product_pricelist_item(models.Model):
    _inherit = 'product.pricelist.item'

    description = fields.Char(string='Description')
    compute_price = fields.Selection(selection_add=[('python', 'Python Code')])
    applied_on = fields.Selection(selection_add=[('4_multi', 'Multiple Conditions')])
    max_quantity = fields.Integer(string='Max Quantity')
    python_code = fields.Text(string='Python Code')
    not_multiple_condition = fields.Boolean(string='Not Multiple Condition', default=False)
    product_tmpl_ids = fields.Many2many(comodel_name='product.template',
                                        relation='numa_product_template_pricelist_item_rel', column1='product_tmpl_id',
                                        column2='pricelist_item_id', string='Product Template')
    product_ids = fields.Many2many(comodel_name='product.product', relation='numa_product_product_pricelist_item_rel',
                                   column1='product_id', column2='pricelist_item_id', string='Products')
    product_category_ids = fields.Many2many(comodel_name='product.category',
                                            relation='numa_product_category_pricelist_item_rel',
                                            column1='product_category_id', column2='pricelist_item_id',
                                            string='Product Categories')
    product_trademark_ids = fields.Many2many(comodel_name='product.trademark',
                                             relation='numa_product_trademark_pricelist_item_rel',
                                             column1='product_trademark_id', column2='pricelist_item_id',
                                             string='Product Trademark')
    product_lot_ids = fields.Many2many(comodel_name='stock.production.lot',
                                       relation='numa_product_lot_pricelist_item_rel', column1='lot_id',
                                       column2='pricelist_item_id', string='Lotes')
    product_serial_ids = fields.Many2many(comodel_name='product.serial_number',
                                          relation='numa_product_serial_pricelist_item_rel',
                                          column1='product_serial_id', column2='pricelist_item_id', string='Seriales')
    partner_ids = fields.Many2many(comodel_name='res.partner', relation='numa_partner_pricelist_item_rel',
                                   column1='partner_id', column2='pricelist_item_id', string='Partners')
    partner_category_ids = fields.Many2many(comodel_name='res.partner.category',
                                            relation='numa_partner_category_pricelist_item_rel',
                                            column1='partner_category_id', column2='pricelist_item_id',
                                            string='Partner Categories')
    afip_punto_venta_ids = fields.Many2many(comodel_name='afip.punto_venta',
                                            relation='numa_afip_punto_venta_pricelist_item_rel',
                                            column1='punto_venta_id', column2='pricelist_item_id',
                                            string='Puntos de Venta')
    partner_seller_ids = fields.Many2many(comodel_name='res.users', relation='numa_partner_seller_pricelist_item_rel',
                                          column1='user_id', column2='pricelist_item_id', string='Vendedor')
    city_ids = fields.Many2many(comodel_name='numa.city', relation='numa_city_pricelist_item_rel',
                                column1='country_city_id', column2='pricelist_item_id', string='Ciudades')
    state_ids = fields.Many2many(comodel_name='res.country.state', relation='numa_state_pricelist_item_rel',
                                 column1='country_state_id', column2='pricelist_item_id', string='States')
    country_ids = fields.Many2many(comodel_name='res.country', relation='numa_country_pricelist_item_rel',
                                   column1='country_id', column2='pricelist_item_id', string='Countries')
    product_bonificado_ids = fields.One2many(comodel_name='product.pricelist.bonificado',
                                             inverse_name='pricelist_item_id', string='Productos Bonificados')

    base = fields.Selection(
        selection_add=[('pricelist_base', 'Price List Base'), ('supplier_list', "First supplier's list cost"),
                       ('supplier_actual', "First supplier's actual cost")])
    pricelist_base_id = fields.Many2one(comodel_name='numa.product_pricelist_base', string='Price List Base',
                                        ondelete='restrict')
    apply_text = fields.Text(string='Condiciones', compute='_get_pricelist_item_apply_text', store=True)
    note = fields.Text(string='Note')

    @api.one
    @api.depends('categ_id', 'product_tmpl_id', 'product_id', 'compute_price', 'fixed_price', 'pricelist_id',
                 'percent_price', 'price_discount', 'price_surcharge',
                 'product_tmpl_ids', 'product_ids', 'product_category_ids', 'product_category_ids',
                 'product_trademark_ids',
                 'product_lot_ids', 'product_serial_ids', 'partner_ids', 'partner_category_ids', 'afip_punto_venta_ids',
                 'partner_seller_ids', 'city_ids', 'state_ids', 'country_ids', 'applied_on', 'not_multiple_condition')
    def _get_pricelist_item_name_price(self):
        self.name = ''
        if self.applied_on == '0_product_variant':
            if self.product_id:
                self.name = self.product_id.name + ' ' + self.product_id.attribute_values_display + ' ' + self.product_id.product_trademark_id.name
        elif self.applied_on == '1_product':
            if self.product_tmpl_id:
                self.name = self.product_tmpl_id.name + ' ' + self.product_tmpl_id.product_trademark_id.name
        elif self.applied_on == '2_product_category':
            if self.categ_id:
                self.name = _("Category: %s") % (self.categ_id.name)
        elif self.applied_on == '3_global':
            self.name = _("Todos los Productos")
        else:
            lista = []
            if self.product_tmpl_ids:
                lista.append(_("Plantilla Producto"))
            if self.product_ids:
                lista.append(_("Variante Producto"))
            if self.product_category_ids:
                lista.append(_("Categoria Producto"))
            if self.product_trademark_ids:
                lista.append(_("Marca Producto"))
            if self.product_lot_ids:
                lista.append(_("Lote Producto"))
            if self.product_serial_ids:
                lista.append(_("Serial Producto"))
            if self.partner_ids:
                lista.append(_("Empresa"))
            if self.partner_category_ids:
                lista.append(_("Categoria Empresa"))
            if self.afip_punto_venta_ids:
                lista.append(_("Punto Venta"))
            if self.partner_seller_ids:
                lista.append(_("Vendedores"))
            if self.city_ids:
                lista.append(_("Ciudades"))
            if self.state_ids:
                lista.append(_("Provincias"))
            if self.country_ids:
                lista.append(_("Paises"))
            if lista:
                self.name = ' - '.join(lista)
            else:
                self.name = 'No hay condiciones definidas'

        if self.compute_price == 'fixed':
            self.price = ("%s %s") % (self.fixed_price, self.pricelist_id.currency_id.name)
        elif self.compute_price == 'percentage':
            self.price = _("%s %% discount") % (self.percent_price)
        elif self.compute_price == 'python':
            self.price = _("Codigo Python")
        else:
            self.price = _("%s %% discount and %s surcharge") % (abs(self.price_discount), self.price_surcharge)

    @api.one
    @api.depends('product_tmpl_ids', 'product_ids', 'product_category_ids', 'product_category_ids',
                 'product_trademark_ids',
                 'product_lot_ids', 'product_serial_ids', 'partner_ids', 'partner_category_ids', 'afip_punto_venta_ids',
                 'partner_seller_ids', 'city_ids', 'state_ids', 'country_ids', 'applied_on', 'not_multiple_condition')
    def _get_pricelist_item_apply_text(self):
        if self.applied_on == '4_multi':
            if self.not_multiple_condition:
                self.apply_text = "Ninguna de las siguientes condiciones\n"
            else:
                self.apply_text = "Todas las siguientes condiciones\n"
            if self.product_tmpl_ids:
                self.apply_text = self.apply_text + '\nPlantilla de Productos:'
                lista = ''
                for registro in self.product_tmpl_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.product_ids:
                self.apply_text = self.apply_text + '\nVariantes de Productos:'
                lista = ''
                for registro in self.product_ids:
                    lista = lista + '- ' + registro.name + ' ' + registro.attribute_values_display + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.product_category_ids:
                self.apply_text = self.apply_text + '\nCategorias de Productos:'
                lista = ''
                for registro in self.product_category_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.product_trademark_ids:
                self.apply_text = self.apply_text + '\nMarcas de Productos:'
                lista = ''
                for registro in self.product_trademark_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.product_lot_ids:
                self.apply_text = self.apply_text + '\nLotes de Productos:'
                lista = ''
                for registro in self.product_lot_ids:
                    lista = lista + '- ' + registro.name + '  (' + registro.product_id.name + ' ' + registro.product_id.attribute_values_display + ')\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.product_serial_ids:
                self.apply_text = self.apply_text + '\nSeriales de Productos:'
                lista = ''
                for registro in self.product_serial_ids:
                    lista = lista + '- ' + registro.name + '  (' + registro.product_id.name + ' ' + registro.product_id.attribute_values_display + ')\n'
                self.apply_text = self.apply_text + '\n' + lista

            if self.partner_ids:
                self.apply_text = self.apply_text + '\nEmpresas:'
                lista = ''
                for registro in self.partner_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.partner_category_ids:
                self.apply_text = self.apply_text + '\nCategorias de Empresas:'
                lista = ''
                for registro in self.partner_category_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.afip_punto_venta_ids:
                self.apply_text = self.apply_text + '\nPuntos de Venta:'
                lista = ''
                for registro in self.afip_punto_venta_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.partner_seller_ids:
                self.apply_text = self.apply_text + '\nVendedores:'
                lista = ''
                for registro in self.partner_seller_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista

            if self.city_ids:
                self.apply_text = self.apply_text + '\nCiudades:'
                lista = ''
                for registro in self.city_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.state_ids:
                self.apply_text = self.apply_text + '\nProvincias:'
                lista = ''
                for registro in self.state_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista
            if self.country_ids:
                self.apply_text = self.apply_text + '\nPaises:'
                lista = ''
                for registro in self.country_ids:
                    lista = lista + '- ' + registro.name + '\n'
                self.apply_text = self.apply_text + '\n' + lista


class product_pricelist_bonificado(models.Model):
    _name = 'product.pricelist.bonificado'

    pricelist_item_id = fields.Many2one(comodel_name='product.pricelist.item', string='Price List Item',
                                        ondelete='restrict')
    product_id = fields.Many2one(comodel_name='product.product', string='Variante Producto', ondelete='restrict')
    quantity = fields.Float(string='Cantidad')


class numa_product_pricelist_base(models.Model):
    _name = 'numa.product_pricelist_base'

    name = fields.Char(string='Price List', size=128, translate=True, required=True)
    description = fields.Char(string='Description')
    pricelist_active = fields.Boolean(string='Active', default=True)
    pricelist_company_id = fields.Many2one(comodel_name='res.company', string='Company', required=True,
                                           ondelete='restrict')
    pricelist_currency_id = fields.Many2one(comodel_name='res.currency', string='Moneda', required=True,
                                            ondelete='restrict')
    pricelist_type = fields.Selection([('sale', 'Sale'), ('purchase', 'Purchase'), ('reference', 'Reference')],
                                      string='Price List Type', required=True, default='sale')
    pricelist_version_ids = fields.One2many(comodel_name='numa.product_pricelist_base_version',
                                            inverse_name='pricelist_id', string='Versions')
    pricelist_product_ids = fields.Many2many(comodel_name='product.product', relation='numa_product_pricelist_base_rel',
                                             column1='pricelist_base_id', column2='product_id',
                                             string='Products Selected')
    note = fields.Text(string='Note')

    @api.multi
    def action_new_pricelist_version(self):
        new_pricelist_version = self.env['numa.product_pricelist_base_version_new'].create(
            {'pricelist_base_id': self.id})

        return {'name': _("New Price List Version to ") + self.name,
                'view_mode': 'form',
                'view_type': 'form',
                'res_model': 'numa.product_pricelist_base_version_new',
                'type': 'ir.actions.act_window',
                'res_id': new_pricelist_version.id,
                'target': 'new',
                'nodestroy': False,
                }


class numa_product_pricelist_base_version_new(models.TransientModel):
    _name = 'numa.product_pricelist_base_version_new'

    name = fields.Char(string='Name', size=128)
    description = fields.Char(string='Description')
    pricelist_base_id = fields.Many2one(comodel_name='numa.product_pricelist_base', string='Price List', required=True,
                                        ondelete='restrict')
    new_pricelist_base_version_based = fields.Selection(
        [('pricelist_version', 'Price List Version'), ('product_selected', 'Product Selected'), ('none', 'None')],
        string='Based in', required=True, default='none')
    pricelist_base_version_id = fields.Many2one(comodel_name='numa.product_pricelist_base_version',
                                                string='Price List Base Version')
    percentage_on_price = fields.Float(string='Apply Percentage')
    date_valid_from = fields.Date(string='Valid From')
    date_valid_to = fields.Date(string='Valid To')
    note = fields.Text(string='Note')

    @api.multi
    def action_generate_version(self):

        new_pricelist_version = self.env['numa.product_pricelist_base_version'].create({'name': self.name,
                                                                                        'description': self.description,
                                                                                        'pricelist_id': self.pricelist_base_id.id,
                                                                                        'date_valid_from': self.date_valid_from,
                                                                                        'date_valid_to': self.date_valid_to,
                                                                                        'product_ids': False,
                                                                                        'note': self.note,
                                                                                        'state': 'draft'})
        if self.new_pricelist_base_version_based == 'pricelist_version':
            if self.pricelist_base_version_id.product_ids:
                for line in self.pricelist_base_version_id.product_ids:
                    self.env['numa.product_pricelist_base_version_items'].create(
                        {'pricelist_version_base_id': new_pricelist_version.id,
                         'product_id': line.product_id.id,
                         'item_price': line.item_price * (1 + self.percentage_on_price / 100)})
        if self.new_pricelist_base_version_based == 'product_selected':
            if self.pricelist_base_id.pricelist_product_ids:
                for line in self.pricelist_base_id.pricelist_product_ids:
                    self.env['numa.product_pricelist_base_version_items'].create(
                        {'pricelist_version_base_id': new_pricelist_version.id,
                         'product_id': line.id,
                         'item_price': 0.0})
        return False


class numa_product_pricelist_base_version(models.Model):
    _name = 'numa.product_pricelist_base_version'

    name = fields.Char(string='Name', size=128, translate=True, required=True)
    description = fields.Char(string='Description')
    pricelist_id = fields.Many2one(comodel_name='numa.product_pricelist_base', string='Price List', ondelete='restrict')
    date_valid_from = fields.Date(string='Valid From', required=True)
    date_valid_to = fields.Date(string='Valid To', required=True)
    product_ids = fields.One2many(comodel_name='numa.product_pricelist_base_version_items',
                                  inverse_name='pricelist_version_base_id', string='Products')
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved')], string='State', default='draft')
    note = fields.Text(string='Note')
    pricelist_currency_rel = fields.Char(string='Currency', related='pricelist_id.pricelist_currency_id.name',
                                         readonly=True)
    pricelist_version_active = fields.Boolean(string='Active?', default=True)

    @api.multi
    def action_add_products(self):
        return {'name': _("Select Products for ") + self.pricelist_id.name + " - " + self.name,
                'view_mode': 'tree',
                'view_type': 'form',
                'res_model': 'product.product',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'nodestroy': False,
                }


class numa_product_pricelist_base_version_items(models.Model):
    _name = 'numa.product_pricelist_base_version_items'

    pricelist_version_base_id = fields.Many2one(comodel_name='numa.product_pricelist_base_version',
                                                string='Price List Version', required=True, ondelete='restrict')
    product_id = fields.Many2one(comodel_name='product.product', string='Product', required=True, ondelete='restrict')
    item_price = fields.Float(string='Price')
    date_valid_from_rel = fields.Date(string='Valid From', related='pricelist_version_base_id.date_valid_from')
    date_valid_to_rel = fields.Date(string='Valid To', related='pricelist_version_base_id.date_valid_to')
    pricelist_rel = fields.Char(string='Price List', related='pricelist_version_base_id.pricelist_id.name',
                                readonly=True)
    pricelist_currency_rel = fields.Char(string='Currency',
                                         related='pricelist_version_base_id.pricelist_id.pricelist_currency_id.name',
                                         readonly=True)


class numa_product_template_supplierinfo(models.Model):
    _inherit = 'product.template'

    @api.multi
    def action_supplierinfo(self):
        self.ensure_one()

        return {
            'name': _("Supplier Info"),
            'view_mode': 'tree,form',
            'view_type': 'form',
            'res_model': 'product.supplierinfo',
            'res_id': False,
            'type': 'ir.actions.act_window',
            'target': 'current',
            'domain': [('product_tmpl_id', '=', self.id)],
            'context': {'default_product_tmpl_id': self.id},
            'nodestroy': False,
        }


class numa_product_product_pricelist_item(models.Model):
    _inherit = 'product.product'

    pricelist_item_ids = fields.Many2many(comodel_name='product.pricelist.item',
                                          relation='numa_product_product_pricelist_item_rel',
                                          column1='pricelist_item_id', column2='product_id', string='Price List Items')
    pricelist_product_ids = fields.Many2many(comodel_name='numa.product_pricelist_base',
                                             relation='numa_product_pricelist_base_rel', column1='product_id',
                                             column2='pricelist_base_id', string='Pricelist Base')


class numa_product_category_product_pricelist_item(models.Model):
    _inherit = 'product.category'

    pricelist_item_ids = fields.Many2many(comodel_name='product.pricelist.item',
                                          relation='numa_product_category_pricelist_item_rel',
                                          column1='pricelist_item_id', column2='product_category_id',
                                          string='Price List Items')


class numa_partner_pricelist_item(models.Model):
    _inherit = 'res.partner'

    pricelist_item_ids = fields.Many2many(comodel_name='product.pricelist.item',
                                          relation='numa_partner_pricelist_item_rel', column1='pricelist_item_id',
                                          column2='partner_id', string='Price List Items')


class numa_partner_category_product_pricelist_item(models.Model):
    _inherit = 'res.partner.category'

    pricelist_item_ids = fields.Many2many(comodel_name='product.pricelist.item',
                                          relation='numa_partner_category_pricelist_item_rel',
                                          column1='pricelist_item_id', column2='partner_category_id',
                                          string='Price List Items')


class numa_product_trademark_pricelist_item(models.Model):
    _inherit = 'product.trademark'

    pricelist_item_ids = fields.Many2many(comodel_name='product.pricelist.item',
                                          relation='numa_product_trademark_pricelist_item_rel',
                                          column1='pricelist_item_id', column2='product_trademark_id',
                                          string='Price List Items')


class numa_country_state_pricelist_item(models.Model):
    _inherit = 'res.country.state'

    pricelist_item_ids = fields.Many2many(comodel_name='product.pricelist.item',
                                          relation='numa_state_pricelist_item_rel', column1='pricelist_item_id',
                                          column2='country_state_id', string='Price List Items')


class numa_country_pricelist_item(models.Model):
    _inherit = 'res.country'

    pricelist_item_ids = fields.Many2many(comodel_name='product.pricelist.item',
                                          relation='numa_country_pricelist_item_rel', column1='pricelist_item_id',
                                          column2='country_id', string='Price List Items')

