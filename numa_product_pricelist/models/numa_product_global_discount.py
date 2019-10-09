# -*- coding: utf-8 -*-
# ##############################################################################
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


from openerp import fields, models, api 
from openerp.tools.translate import _
import odoo.addons.decimal_precision as dp
from openerp.exceptions import ValidationError

class numa_product_pricelist_global_discount(models.Model):
    _inherit = 'product.pricelist'
    
    global_discount_count = fields.Integer('# Descuentos Globales', compute='_compute_global_discount_count')
    discount_ids = fields.One2many(comodel_name='product.global_discount.item', inverse_name='pricelist_id',
                                             string='Descuentos Globales')

    @api.multi
    def action_global_discount_items(self):
        self.ensure_one()

        return {
            'name': _("Descuentos Globales"),
            'view_mode': 'tree,form',
            'view_type': 'form',
            'res_model': 'product.global_discount.item',
            'res_id': False,
            'type': 'ir.actions.act_window',
            'target': 'current',
            'domain': [('pricelist_id', '=', self.id)],
            'context': {'default_pricelist_id': self.id},
            'nodestroy': False,
        }
        
    def _compute_global_discount_count(self):
        read_group_res = self.env['product.global_discount.item'].read_group([('pricelist_id', 'in', self.ids)], ['pricelist_id'], ['pricelist_id'])
        mapped_data = dict([(data['pricelist_id'][0], data['pricelist_id_count']) for data in read_group_res])
        for pricelist in self:
            pricelist.global_discount_count = mapped_data.get(pricelist.id, 0)

    def compute_discounts(self,
                          sale_order_id,
                          invoice_id,
                          issuer_id,
                          sales_point_id,
                          partner_id,
                          destination_address,
                          lines,
                          afip_punto_de_venta=None,
                          salesman=None,
                          date=None,
                          outputDiscounts=[]):
        self.ensure_one()
        pricelist = self
        if not date:
            date = self._context.get('date') or fields.Date.context_today(self)

        discountsPerRule = {}

        for line in lines:
            for rule in pricelist.discount_ids:
                if rule.date_start and date < rule.date_start:
                    continue
                if rule.date_end and date > rule.date_end:
                    continue

                if not rule.applied_on == '3_global':
                    if not rule.applied_on == '4_multi':
                        if rule.product_id and \
                            line['product_id'].id != rule.product_id.id:
                            continue
                        if rule.product_tmpl_id and \
                            line['product_tmpl_id'].product_tmpl_id != rule.product_tmpl_id.id:
                            continue
                        if rule.product_id and \
                            line['product_id'].categ_id.id != rule.categ_id.id:
                            continue
                    else:
                        if not rule.not_multiple_condition:
                            if rule.product_tmpl_ids and \
                                    line['product_id'].product_tmpl_id.id not in rule.product_tmpl_ids.ids:
                                continue
                            elif rule.product_ids and \
                                    line['product_id'].id not in rule.product_ids.ids:
                                continue
                            elif rule.product_category_ids and \
                                    line['product_id'].categ_id.id not in rule.product_category_ids.ids:
                                continue
                            elif rule.product_trademark_ids and \
                                    line['product_id'].product_trademark_id.id not in rule.product_trademark_ids:
                                continue
                            elif rule.product_lot_ids and 'lot_id' in line and \
                                    line['lot_id'].id not in rule.product_lot_ids.ids:
                                continue
                            elif rule.product_serial_ids and 'serial_id' in line  and \
                                    line['serial_id'] not in rule.product_serial_ids.ids:
                                continue
                            elif rule.partner_category_ids and partner_id and partner_id.category_id and \
                                    partner_id.category_id.id not in rule.partner_category_ids:
                                continue
                            elif rule.afip_punto_venta_ids and afip_punto_de_venta and \
                                    afip_punto_de_venta.id not in rule.afip_punto_venta_ids:
                                continue
                            elif rule.partner_seller_ids and salesman and \
                                    salesman.id not in rule.partner_seller_ids.ids:
                                continue
                            elif rule.city_ids and destination_address.city_id and \
                                    destination_address.city_id not in rule.city_ids.ids:
                                continue
                            elif rule.state_ids and destination_address.city_id.country_state_id and \
                                    destination_address.country_state_id.id not in rule.state_ids.ids:
                                continue
                            elif rule.country_ids and destination_address.city_id.country_id and \
                                    destination_address.city_id.country_id.id not in rule.country_ids.ids:
                                continue
                        else:
                            if rule.product_tmpl_ids and \
                                    line['product_id'].product_tmpl_id.id in rule.product_tmpl_ids.ids:
                                continue
                            elif rule.product_ids and \
                                    line['product_id'].id in rule.product_ids.ids:
                                continue
                            elif rule.product_category_ids and \
                                    line['product_id'].categ_id.id in rule.product_category_ids.ids:
                                continue
                            elif rule.product_trademark_ids and \
                                    line['product_id'].product_trademark_id.id in rule.product_trademark_ids:
                                continue
                            elif rule.product_lot_ids and 'lot_id' in line and \
                                    line['lot_id'].id in rule.product_lot_ids.ids:
                                continue
                            elif rule.product_serial_ids and 'serial_id' in line  and \
                                    line['serial_id'] in rule.product_serial_ids.ids:
                                continue
                            elif rule.partner_category_ids and partner_id and partner_id.category_id and \
                                    partner_id.category_id.id in rule.partner_category_ids:
                                continue
                            elif rule.afip_punto_venta_ids and afip_punto_de_venta and \
                                    afip_punto_de_venta.id in rule.afip_punto_venta_ids:
                                continue
                            elif rule.partner_seller_ids and salesman and \
                                    salesman.id in rule.partner_seller_ids.ids:
                                continue
                            elif rule.city_ids and destination_address.city_id and \
                                    destination_address.city_id in rule.city_ids.ids:
                                continue
                            elif rule.state_ids and destination_address.city_id.country_state_id and \
                                    destination_address.country_state_id.id in rule.state_ids.ids:
                                continue
                            elif rule.country_ids and destination_address.city_id.country_id and \
                                    destination_address.city_id.country_id.id in rule.country_ids.ids:
                                continue

                # Aplicar la regla

                # Regla recursiva
                if rule.base_pricelist_id:
                    rule.base_pricelist_id.compute_discounts(
                        sale_order_id,
                        invoice_id,
                        issuer_id,
                        sales_point_id, partner_id,
                        destination_address,
                        lines,
                        afip_punto_de_venta=afip_punto_de_venta,
                        salesman=salesman,
                        date=date,
                        outputDiscounts=outputDiscounts
                    )

                # Descuentos propios

                if rule.id not in discountsPerRule:
                    discountsPerRule[rule.id] = {
                        'rule': rule,
                        'tax': {},
                    }
                taxData = discountsPerRule[rule.id]['tax']
                # Inicialización
                if rule.compute_price == 'fixed':
                    pass
                elif rule.compute_price == 'percentage':
                    pass
                elif rule.compute_price == 'formula':
                    pass
                elif rule.compute_price == 'carry_pay':
                    taxData['perProduct'] = {}
                elif rule.compute_price == 'segunda_unidad':
                    pass
                elif rule.compute_price == 'productos':
                    pass
                elif rule.compute_price == 'python':
                    pass

                # Aplicación
                for tax_id in line['tax_ids']:
                    if tax_id.id not in taxData:
                        taxData[tax_id.id] = {}
                        taxData[tax_id.id]['base'] = 0.0
                        taxData[tax_id.id]['amount'] = 0.0
                        taxData[tax_id.id]['tax_percent'] = tax_id.amount
                        taxData[tax_id.id]['tax_amount'] = 0.0

                    if rule.compute_price == 'fixed':
                        taxData['amount'] += rule.fixed_price
                        taxData[tax_id.id]['tax_amount'] += taxData[tax_id.id]['amount'] * taxData[tax_id.id]['tax_percent']
                    elif rule.compute_price == 'percentage':
                        taxData[tax_id.id]['base'] += line['subtotal']
                        taxData[tax_id.id]['amount'] += line['subtotal'] * rule.percent_price / 100.0
                        taxData[tax_id.id]['tax_amount'] = taxData[tax_id.id]['amount'] * taxData[tax_id.id]['tax_percent'] / 100.0
                    elif rule.compute_price == 'formula':
                        pass
                    elif rule.compute_price == 'carry_pay':
                        if line.product_id.id not in taxData['perProduct']:
                            taxData['perProduct'][line['product_id'].id] = {
                                'acumulatedQuantity': line['quantity'],
                                'product': line['product_id'],
                                'price_unit': line['price_unit'],
                            }
                        ppData = taxData['perProduct'][line['product_id'].id]
                        ppData['acumulatedQuantity'] += line['quantity']
                    elif rule.compute_price == 'segunda_unidad':
                        pass
                    elif rule.compute_price == 'productos':
                        pass
                    elif rule.compute_price == 'python':
                        pass

                break

        # Procesamiento final

        for dpr in discountsPerRule.values():
            if rule.compute_price == 'fixed':
                pass
            elif rule.compute_price == 'percentage':
                for tax_id in dpr['tax']:
                    outputDiscounts.append({
                        #'rule_id': dpr['rule'].id,
                        'sale_order_id': sale_order_id,
                        'invoice_id': invoice_id,
                        'display_discount_name': dpr['rule'].name,
                        'base': dpr['tax'][tax_id]['base'],
                        'percent': dpr['rule'].percent_price,
                        'amount': dpr['tax'][tax_id]['amount'],
                        'account_id': dpr['rule'].account_id.id,
                        'tax_id': tax_id,
                        'amount_tax': dpr['tax'][tax_id]['tax_amount'],
                        'product_id': False,
                        'product_tmpl_id': False,
                        'product_trademark_id': False,
                        'product_lot_id': False,
                        'product_serial_id': False,
                        'product_category_id': False,
                    })
            elif rule.compute_price == 'formula':
                pass
            elif rule.compute_price == 'carry_pay':
                for productData in taxData['perProduct'].values():
                    if productData['acumulatedQuantity'] > rule.lleveX:
                        quantity = productData['acumulatedQuantity'] // rule.lleveX * (rule.lleveX - rule.pagueY)
                        if rule.max_products:
                            quantity = min(rule.max_products, quantity)
                        amount = quantity * productData['price_unit']
                        outputDiscounts.append({
                            'rule_id': rule.id,
                            'numa_display_name': rule.name,
                            'base': rule.lleveX * productData['price_unit'] * quantity,
                            'percent': 0.0,
                            'amount': (rule.lleveX - rule.pagueY) * line['price_unit'],
                            'tax_id': taxData['tax'].id,
                            'amount_tax': taxData['tax'].factor * amount,
                            'product_id': productData['product'].id,
                            'product_tmpl_id': productData['product'].product_tmpl_id.d,
                            'product_trademark_id': False,
                            'product_lot_id': False,
                            'product_serial_id': False,
                            'product_category_id': False,
                        })
            elif rule.compute_price == 'segunda_unidad':
                pass
            elif rule.compute_price == 'productos':
                pass
            elif rule.compute_price == 'python':
                pass

        return [o for o in outputDiscounts if o['amount'] > 0]

class numa_product_global_discount_item(models.Model):
    _name = 'product.global_discount.item'
    _description = "Global Discount item"
    _order = "sequence asc, applied_on, categ_id desc, id"

    product_tmpl_id = fields.Many2one('product.template', 'Product Template', ondelete='cascade',help="Specify a template if this rule only applies to one product template. Keep empty otherwise.")
    product_id = fields.Many2one('product.product', 'Product', ondelete='cascade',help="Specify a product if this rule only applies to one product. Keep empty otherwise.")
    categ_id = fields.Many2one('product.category', 'Product Category', ondelete='cascade',help="Specify a product category if this rule only applies to products belonging to this category or its children categories. Keep empty otherwise.")
    applied_on = fields.Selection([('3_global', 'Global'),('2_product_category', ' Product Category'),('1_product', 'Product'),('0_product_variant', 'Product Variant'),('4_multi','Multiple Conditions')], "Apply On",default='3_global', required=True,help='Pricelist Item applicable on selected option')
    carry = fields.Integer(string='Lleve')
    pay = fields.Integer(string='Pague')
    carry_pay_quantity = fields.Integer(string='Limite')
    segunda_unidad_quantity = fields.Integer(string='Limite')
    sequence = fields.Integer('Sequence', default=5, required=True,help="Gives the order in which the pricelist items will be checked. The evaluation gives highest priority to lowest sequence and stops as soon as a matching item is found.")
    base = fields.Selection([('document','Documento'),('pricelist', 'Otra Lista de Precios')], "Basado en",default='document', required=True,help='Base price for computation.')
    base_pricelist_id = fields.Many2one('product.pricelist', 'Otra Lista de Precios')
    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist', index=True, ondelete='cascade')
    price_surcharge = fields.Float('Price Surcharge', digits=dp.get_precision('Product Price'),help='Specify the fixed amount to add or substract(if negative) to the amount calculated with the discount.')
    price_discount = fields.Float('Price Discount', default=0, digits=(16, 2))
    price_round = fields.Float('Price Rounding', digits=dp.get_precision('Product Price'),help="Sets the price so that it is a multiple of this value.\n"
                                                                                               "Rounding is applied after the discount and before the surcharge.\n"
                                                                                               "To have prices that end in 9.99, set rounding 10, surcharge -0.01")
    price_min_margin = fields.Float('Min. Price Margin', digits=dp.get_precision('Product Price'),help='Specify the minimum amount of margin over the base price.')
    price_max_margin = fields.Float('Max. Price Margin', digits=dp.get_precision('Product Price'),help='Specify the maximum amount of margin over the base price.')
    company_id = fields.Many2one('res.company', 'Company',readonly=True, related='pricelist_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', 'Currency',readonly=True, related='pricelist_id.currency_id', store=True)
    date_start = fields.Date('Start Date', help="Starting date for the pricelist item validation")
    date_end = fields.Date('End Date', help="Ending valid for the pricelist item validation")
    compute_price = fields.Selection([('fixed', 'Monto Fijo'),('percentage', 'Porcentaje (descuento)'),('formula', 'Formula'),('carry_pay','Lleve x Pague y'),('segunda_unidad','2da Unidad'),('productos','Productos Bonificados'),('python','Codigo Python')], index=True, default='percentage')
    type_amount_total = fields.Selection([('neto', 'Neto'),('total', 'Total')], string='Sobre Importe',default='neto')
    amount_total = fields.Float('Mayor o igual', digits=dp.get_precision('Product Price'),help='Aplica a importe iguale o mayor en la Factura.')
    account_id = fields.Many2one('account.account', string=u'Cuenta Contable', required=True)
    percent_price = fields.Float('Percentage Price')
    fixed_price = fields.Float('Monto Fijo (descuento)', digits=dp.get_precision('Product Price'),help='Monto a descontar del importe total.')
    # functional fields used for usability purposes
    name = fields.Char('Name', compute='_get_global_discount_item_name_price',help="Explicit rule name for this pricelist line.")
    price = fields.Char('Price', compute='_get_global_discount_item_name_price',help="Explicit rule name for this pricelist line.")

    description = fields.Char(string='Description')
    python_code = fields.Text(string='Python Code')
    not_multiple_condition = fields.Boolean(string='Not Multiple Condition', default=False)
    product_tmpl_ids = fields.Many2many(comodel_name='product.template', relation='numa_product_template_global_discount_item_rel', column1='product_tmpl_id', column2='global_discount_item_id', string='Product Template')
    product_ids = fields.Many2many(comodel_name='product.product', relation='numa_product_product_global_discount_item_rel', column1='product_id', column2='global_discount_item_id', string='Products')
    product_category_ids = fields.Many2many(comodel_name='product.category', relation='numa_product_category_global_discount_item_rel', column1='product_category_id', column2='global_discount_item_id', string='Product Categories')
    product_trademark_ids = fields.Many2many(comodel_name='product.trademark', relation='numa_product_trademark_global_discount_item_rel', column1='product_trademark_id', column2='global_discount_item_id', string='Product Trademark')
    product_lot_ids = fields.Many2many(comodel_name='stock.production.lot', relation='numa_product_lot_global_discount_item_rel', column1='lot_id', column2='global_discount_item_id', string='Lotes')
    product_serial_ids = fields.Many2many(comodel_name='product.serial_number', relation='numa_product_serial_global_discount_item_rel', column1='product_serial_id', column2='global_discount_item_id', string='Seriales')
    partner_ids = fields.Many2many(comodel_name='res.partner', relation='numa_partner_global_discount_item_rel', column1='partner_id', column2='global_discount_item_id', string='Partners')
    partner_category_ids = fields.Many2many(comodel_name='res.partner.category', relation='numa_partner_category_global_discount_item_rel', column1='partner_category_id', column2='global_discount_item_id', string='Partner Categories')
    afip_punto_venta_ids = fields.Many2many(comodel_name='afip.punto_venta', relation='numa_afip_punto_venta_global_discount_item_rel', column1='punto_venta_id', column2='global_discount_item_id', string='Puntos de Venta')
    partner_seller_ids = fields.Many2many(comodel_name='res.users', relation='numa_partner_seller_global_discount_item_rel', column1='user_id', column2='global_discount_item_id', string='Vendedor')
    city_ids = fields.Many2many(comodel_name='numa.city', relation='numa_city_global_discount_item_rel', column1='country_city_id', column2='global_discount_item_id', string='Ciudades')
    state_ids = fields.Many2many(comodel_name='res.country.state', relation='numa_state_global_discount_item_rel', column1='country_state_id', column2='global_discount_item_id', string='States')
    country_ids = fields.Many2many(comodel_name='res.country', relation='numa_country_global_discount_item_rel', column1='country_id', column2='global_discount_item_id', string='Countries')
    product_bonificado_ids = fields.One2many(comodel_name='product.pricelist_global_discount.bonificado',inverse_name='global_discount_item_id',string='Productos Bonificados')    
    
    pricelist_base_id = fields.Many2one(comodel_name='numa.product_pricelist_base', string='Price List Base', ondelete='restrict')
    apply_text = fields.Text(string='Condiciones',compute='_get_global_discount_item_apply_text',store=True)
    note = fields.Text(string='Note')

    @api.constrains('base_pricelist_id', 'pricelist_id', 'base')
    def _check_recursion(self):
        if any(item.base == 'pricelist' and item.pricelist_id and item.pricelist_id == item.base_pricelist_id for item in self):
            raise ValidationError(_('Error! You cannot assign the Main Pricelist as Other Pricelist in PriceList Item!'))
        return True
        
    @api.one
    @api.depends('categ_id', 'product_tmpl_id', 'product_id', 'compute_price', 'fixed_price','pricelist_id', 'percent_price', 'price_discount', 'price_surcharge',
                 'product_tmpl_ids', 'product_ids', 'product_category_ids', 'product_category_ids', 'product_trademark_ids',
                 'product_lot_ids', 'product_serial_ids', 'partner_ids', 'partner_category_ids','afip_punto_venta_ids',
                 'partner_seller_ids','city_ids','state_ids','country_ids','applied_on','not_multiple_condition')
    def _get_global_discount_item_name_price(self):
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
                self.name = 'Descuento Global'

        if self.compute_price == 'fixed':
            self.price = ("%s %s") % (self.fixed_price, self.pricelist_id.currency_id.name)
        elif self.compute_price == 'percentage':
            self.price = _("%s %% discount") % (self.percent_price)
        elif self.compute_price == 'productos':
            self.price = _("Productos Bonificados")
        elif self.compute_price == 'python':
            self.price = _("Codigo Python")
        else:
            self.price = _("%s %% discount and %s surcharge") % (abs(self.price_discount), self.price_surcharge)

    @api.one
    @api.depends('product_tmpl_ids', 'product_ids', 'product_category_ids', 'product_category_ids', 'product_trademark_ids',
                 'product_lot_ids', 'product_serial_ids', 'partner_ids', 'partner_category_ids','afip_punto_venta_ids',
                 'partner_seller_ids','city_ids','state_ids','country_ids','applied_on','not_multiple_condition')
    def _get_global_discount_item_apply_text(self):
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


            
class product_pricelist_global_discount_bonificado(models.Model):
    _name = 'product.pricelist_global_discount.bonificado'
    
    global_discount_item_id = fields.Many2one(comodel_name='product.global_discount.item', string='Global Discount Item', ondelete='restrict')
    product_id = fields.Many2one(comodel_name='product.product', string='Variante Producto', ondelete='restrict')
    quantity = fields.Float(string='Cantidad')

class numa_product_product_global_discount_item(models.Model):
    _inherit = 'product.product'

    global_discount_item_ids = fields.Many2many(comodel_name='product.global_discount.item', relation='numa_product_product_global_discount_item_rel', column1='global_discount_item_id', column2='product_id', string='Global Discount Items')

class numa_product_category_product_pricelist_item(models.Model):
    _inherit = 'product.category'

    global_discount_item_ids = fields.Many2many(comodel_name='product.global_discount.item', relation='numa_product_category_global_discount_item_rel', column1='global_discount_item_id', column2='product_category_id', string='Global Discount Items')

class numa_partner_pricelist_item(models.Model):
    _inherit = 'res.partner'

    global_discount_item_ids = fields.Many2many(comodel_name='product.global_discount.item', relation='numa_partner_global_discount_item_rel', column1='global_discount_item_id', column2='partner_id', string='Global Discount Items')

class numa_partner_category_product_pricelist_item(models.Model):
    _inherit = 'res.partner.category'

    global_discount_item_ids = fields.Many2many(comodel_name='product.global_discount.item', relation='numa_partner_category_global_discount_item_rel', column1='global_discount_item_id', column2='partner_category_id', string='Global Discount Items')

class numa_product_trademark_pricelist_item(models.Model):
    _inherit = 'product.trademark'

    global_discount_item_ids = fields.Many2many(comodel_name='product.global_discount.item', relation='numa_product_trademark_global_discount_item_rel', column1='global_discount_item_id', column2='product_trademark_id', string='Global Discount Items')

class numa_country_state_pricelist_item(models.Model):
    _inherit = 'res.country.state'

    global_discount_item_ids = fields.Many2many(comodel_name='product.global_discount.item', relation='numa_state_global_discount_item_rel', column1='global_discount_item_id', column2='country_state_id', string='Global Discount Items')
    
class numa_country_pricelist_item(models.Model):
    _inherit = 'res.country'

    global_discount_item_ids = fields.Many2many(comodel_name='product.global_discount.item', relation='numa_country_global_discount_item_rel', column1='global_discount_item_id', column2='country_id', string='Global Discount Items')


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
