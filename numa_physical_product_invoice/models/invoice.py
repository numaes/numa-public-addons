from odoo import fields, models, api

import logging
_logger = logging.getLogger(__name__)

UNIT_PER_TYPE = {
    'length': 'm',
    'width': 'm',
    'height': 'm',
    'surface': 'm²',
    'volume': 'm³',
    'weight': 'kg',
}

FIELD_NAME_PER_TYPE = {
    'length': 'product_length',
    'width': 'product_width',
    'height': 'product_height',
    'surface': 'surface',
    'volume': 'volume',
    'weight': 'weight',
}


class Invoice(models.Model):
    _inherit = 'account.move'

    invoice_weight = fields.Float('Weight', compute='_compute_weight_volume')
    invoice_volume = fields.Float('Volume', compute='_compute_weight_volume')

    @api.depends('line_ids')
    def _compute_weight_volume(self):
        for invoice in self:
            if invoice.is_invoice():
                invoice.invoice_weight = 0.0
                invoice.invoice_volume = 0.0
                for line in invoice.invoice_line_ids:
                    invoice.invoice_weight += line.total_weight
                    invoice.invoice_volume += line.total_volume
            else:
                invoice.invoice_weight = 0.0
                invoice.invoice_volume = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        new_invoices = super().create(vals_list)
        new_invoices._compute_amount()
        return new_invoices

    def write(self, vals):
        return super().write(vals)

    def _recompute_tax_lines(self, recompute_tax_base_amount=False):
        ''' Compute the dynamic tax lines of the journal entry.

        :param lines_map: The line_ids dispatched by type containing:
            * base_lines: The lines having a tax_ids set.
            * tax_lines: The lines having a tax_line_id set.
            * terms_lines: The lines generated by the payment terms of the invoice.
            * rounding_lines: The cash rounding lines of the invoice.
        '''
        self.ensure_one()
        in_draft_mode = self != self._origin

        def _serialize_tax_grouping_key(grouping_dict):
            ''' Serialize the dictionary values to be used in the taxes_map.
            :param grouping_dict: The values returned by '_get_tax_grouping_key_from_tax_line' or '_get_tax_grouping_key_from_base_line'.
            :return: A string representing the values.
            '''
            return '-'.join(str(v) for v in grouping_dict.values())

        def _compute_base_line_taxes(base_line):
            ''' Compute taxes amounts both in company currency / foreign currency as the ratio between
            amount_currency & balance could not be the same as the expected currency rate.
            The 'amount_currency' value will be set on compute_all(...)['taxes'] in multi-currency.
            :param base_line:   The account.move.line owning the taxes.
            :return:            The result of the compute_all method.
            '''
            move = base_line.move_id

            if move.is_invoice(include_receipts=True):
                handle_price_include = True
                sign = -1 if move.is_inbound() else 1
                quantity = base_line.price_qty
                is_refund = move.move_type in ('out_refund', 'in_refund')
                price_unit_wo_discount = sign * base_line.price_unit * (1 - (base_line.discount / 100.0))
            else:
                handle_price_include = False
                quantity = 1.0
                tax_type = base_line.tax_ids[0].type_tax_use if base_line.tax_ids else None
                is_refund = (tax_type == 'sale' and base_line.debit) or (tax_type == 'purchase' and base_line.credit)
                price_unit_wo_discount = base_line.amount_currency

            balance_taxes_res = base_line.tax_ids._origin.with_context(force_sign=move._get_tax_force_sign()).compute_all(
                price_unit_wo_discount,
                currency=base_line.currency_id,
                quantity=quantity,
                product=base_line.product_id,
                partner=base_line.partner_id,
                is_refund=is_refund,
                handle_price_include=handle_price_include,
            )

            if move.move_type == 'entry':
                repartition_field = is_refund and 'refund_repartition_line_ids' or 'invoice_repartition_line_ids'
                repartition_tags = base_line.tax_ids.flatten_taxes_hierarchy().mapped(repartition_field).filtered(lambda x: x.repartition_type == 'base').tag_ids
                tags_need_inversion = (tax_type == 'sale' and not is_refund) or (tax_type == 'purchase' and is_refund)
                if tags_need_inversion:
                    balance_taxes_res['base_tags'] = base_line._revert_signed_tags(repartition_tags).ids
                    for tax_res in balance_taxes_res['taxes']:
                        tax_res['tag_ids'] = base_line._revert_signed_tags(self.env['account.account.tag'].browse(tax_res['tag_ids'])).ids

            return balance_taxes_res

        taxes_map = {}

        # ==== Add tax lines ====
        to_remove = self.env['account.move.line']
        for line in self.line_ids.filtered('tax_repartition_line_id'):
            grouping_dict = self._get_tax_grouping_key_from_tax_line(line)
            grouping_key = _serialize_tax_grouping_key(grouping_dict)
            if grouping_key in taxes_map:
                # A line with the same key does already exist, we only need one
                # to modify it; we have to drop this one.
                to_remove += line
            else:
                taxes_map[grouping_key] = {
                    'tax_line': line,
                    'amount': 0.0,
                    'tax_base_amount': 0.0,
                    'grouping_dict': False,
                }
        if not recompute_tax_base_amount:
            self.line_ids -= to_remove

        # ==== Mount base lines ====
        for line in self.line_ids.filtered(lambda line: not line.tax_repartition_line_id):
            # Don't call compute_all if there is no tax.
            if not line.tax_ids:
                if not recompute_tax_base_amount:
                    line.tax_tag_ids = [(5, 0, 0)]
                continue

            compute_all_vals = _compute_base_line_taxes(line)

            # Assign tags on base line
            if not recompute_tax_base_amount:
                line.tax_tag_ids = compute_all_vals['base_tags'] or [(5, 0, 0)]

            tax_exigible = True
            for tax_vals in compute_all_vals['taxes']:
                grouping_dict = self._get_tax_grouping_key_from_base_line(line, tax_vals)
                grouping_key = _serialize_tax_grouping_key(grouping_dict)

                tax_repartition_line = self.env['account.tax.repartition.line'].browse(tax_vals['tax_repartition_line_id'])
                tax = tax_repartition_line.invoice_tax_id or tax_repartition_line.refund_tax_id

                if tax.tax_exigibility == 'on_payment':
                    tax_exigible = False

                taxes_map_entry = taxes_map.setdefault(grouping_key, {
                    'tax_line': None,
                    'amount': 0.0,
                    'tax_base_amount': 0.0,
                    'grouping_dict': False,
                })
                taxes_map_entry['amount'] += tax_vals['amount']
                taxes_map_entry['tax_base_amount'] += self._get_base_amount_to_display(tax_vals['base'], tax_repartition_line, tax_vals['group'])
                taxes_map_entry['grouping_dict'] = grouping_dict
            if not recompute_tax_base_amount:
                line.tax_exigible = tax_exigible

        # ==== Process taxes_map ====
        for taxes_map_entry in taxes_map.values():
            # The tax line is no longer used in any base lines, drop it.
            if taxes_map_entry['tax_line'] and not taxes_map_entry['grouping_dict']:
                if not recompute_tax_base_amount:
                    self.line_ids -= taxes_map_entry['tax_line']
                continue

            currency = self.env['res.currency'].browse(taxes_map_entry['grouping_dict']['currency_id'])

            # Don't create tax lines with zero balance.
            if currency.is_zero(taxes_map_entry['amount']):
                if taxes_map_entry['tax_line'] and not recompute_tax_base_amount:
                    self.line_ids -= taxes_map_entry['tax_line']
                continue

            # tax_base_amount field is expressed using the company currency.
            tax_base_amount = currency._convert(taxes_map_entry['tax_base_amount'], self.company_currency_id, self.company_id, self.date or fields.Date.context_today(self))

            # Recompute only the tax_base_amount.
            if recompute_tax_base_amount:
                if taxes_map_entry['tax_line']:
                    taxes_map_entry['tax_line'].tax_base_amount = tax_base_amount
                continue

            balance = currency._convert(
                taxes_map_entry['amount'],
                self.company_currency_id,
                self.company_id,
                self.date or fields.Date.context_today(self),
            )
            to_write_on_line = {
                'amount_currency': taxes_map_entry['amount'],
                'currency_id': taxes_map_entry['grouping_dict']['currency_id'],
                'debit': balance > 0.0 and balance or 0.0,
                'credit': balance < 0.0 and -balance or 0.0,
                'tax_base_amount': tax_base_amount,
            }

            if taxes_map_entry['tax_line']:
                # Update an existing tax line.
                taxes_map_entry['tax_line'].update(to_write_on_line)
            else:
                create_method = in_draft_mode and self.env['account.move.line'].new or self.env['account.move.line'].create
                tax_repartition_line_id = taxes_map_entry['grouping_dict']['tax_repartition_line_id']
                tax_repartition_line = self.env['account.tax.repartition.line'].browse(tax_repartition_line_id)
                tax = tax_repartition_line.invoice_tax_id or tax_repartition_line.refund_tax_id
                taxes_map_entry['tax_line'] = create_method({
                    **to_write_on_line,
                    'name': tax.name,
                    'move_id': self.id,
                    'partner_id': line.partner_id.id,
                    'company_id': line.company_id.id,
                    'company_currency_id': line.company_currency_id.id,
                    'tax_base_amount': tax_base_amount,
                    'exclude_from_invoice_tab': True,
                    'tax_exigible': tax.tax_exigibility == 'on_invoice',
                    **taxes_map_entry['grouping_dict'],
                })

            if in_draft_mode:
                taxes_map_entry['tax_line'].update(taxes_map_entry['tax_line']._get_fields_onchange_balance(force_computation=True))


class InvoiceLine(models.Model):
    _inherit = 'account.move.line'

    unit_width = fields.Float(string='Unit Width', related='product_id.product_width', readonly=True)
    unit_length = fields.Float(string='Unit Length', related='product_id.product_length', readonly=True)
    unit_height = fields.Float(string='Unit Height', related='product_id.product_height', readonly=True)
    unit_surface = fields.Float(string='Unit Surface', related='product_id.surface', readonly=True)
    unit_weight = fields.Float(string='Unit Weight', related='product_id.weight', readonly=True)
    unit_volume = fields.Float(string='Unit Volume', related='product_id.volume', readonly=True)

    total_surface = fields.Float(string='Total Surface')
    total_weight = fields.Float(string='Total Weight')
    total_volume = fields.Float(string='Total Volume')

    price_qty = fields.Float(string='Price Qty', default=1.0)
    unit_price_uom_id = fields.Many2one('uom.uom', 'Price UoM')

    @api.model_create_multi
    def create(self, vals_list):
        new_records = super().create(vals_list)
        new_records._compute_amount()
        return new_records

    @api.onchange('product_id')
    def product_id_change(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            il.compute_price()
            il.compute_unit_price_uom()
            il.compute_totals()

    @api.onchange('product_uom_id', 'quantity')
    def product_uom_id_change(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            if not il.product_id or not il.product_uom_id:
                continue
            il.compute_unit_price_uom()
            il.compute_totals()

    def compute_unit_price_uom(self):
        uom_model = self.env['uom.uom']

        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            if il.product_id:
                normalized_qty = il.product_uom_id._compute_quantity(il.quantity, il.product_id.uom_id) \
                    if il.product_uom_id else il.quantity
                if il.product_id.price_base == 'normal':
                    il.unit_price_uom_id = il.product_id.uom_id
                    il.price_qty = normalized_qty
                else:
                    il.unit_price_uom_id = uom_model.search(
                        [('name', '=', UNIT_PER_TYPE[il.product_id.price_base])],
                        limit=1
                    )
            else:
                il.unit_price_uom_id = False

    @api.onchange('quantity', 'product_uom_id')
    def compute_totals(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            if not il.product_id or not il.product_uom_id:
                continue

            normalized_qty = il.product_uom_id._compute_quantity(il.quantity, il.product_id.uom_id) \
                if il.product_uom_id else il.quantity
            il.total_surface = normalized_qty * il.unit_surface
            il.total_weight = normalized_qty * il.unit_weight
            il.total_volume = normalized_qty * il.unit_volume

            il._compute_amount()

    @api.onchange('total_surface', 'total_weight', 'total_volume', 'quantity', 'product_uom_id')
    def compute_price(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue

            if not il.product_id:
                il.price_qty = il.quantity
                il._compute_amount()
                continue

            normalized_qty = il.product_uom_id._compute_quantity(il.quantity, il.product_id.uom_id) \
                             if il.product_uom_id else il.quantity
            price_type = il.product_id.price_base
            if price_type == 'length':
                price_qty = il.unit_length * normalized_qty
            elif price_type == 'width':
                price_qty = il.unit_width * normalized_qty
            elif price_type == 'height':
                price_qty = il.unit_height * normalized_qty
            elif price_type == 'surface':
                price_qty = il.total_surface
            elif price_type == 'weight':
                price_qty = il.total_weight
            elif price_type == 'volume':
                price_qty = il.total_volume
            else:
                price_qty = normalized_qty
            il.price_qty = price_qty
            il._compute_amount()

    @api.onchange('price_qty', 'price_unit', 'tax_ids')
    @api.depends('price_qty', 'price_unit', 'tax_ids')
    def _compute_amount(self):
        for il in self:
            if not il.move_id.is_invoice(include_receipts=True):
                continue
            if il.product_id and il.move_id and il.move_id.partner_id:
                taxes = il.tax_ids.compute_all(il.price_unit * (1.00 - (il.discount / 100.0)), il.move_id.currency_id,
                                               il.price_qty, product=il.product_id, partner=il.move_id.partner_id)
                il.update({
                    'price_total': taxes['total_included'],
                    'price_subtotal': taxes['total_excluded'],
                })
                il.flush()
                il.update(il._get_fields_onchange_subtotal())
                il._onchange_balance()
                il._onchange_amount_currency()

    def _get_fields_onchange_balance(self, quantity=None, discount=None, amount_currency=None, move_type=None, currency=None, taxes=None, price_subtotal=None, force_computation=False):
        self.ensure_one()
        return self._get_fields_onchange_balance_model(
            quantity=quantity or self.quantity if self.product_id.price_base == 'normal' else self.price_qty,
            discount=discount or self.discount,
            amount_currency=amount_currency or self.amount_currency,
            move_type=move_type or self.move_id.move_type,
            currency=currency or self.currency_id or self.move_id.currency_id,
            taxes=taxes or self.tax_ids,
            price_subtotal=price_subtotal or self.price_qty * self.price_unit * (1.0 - self.discount/100.0),
            force_computation=force_computation,
        )

    @api.onchange('quantity', 'discount', 'price_unit', 'tax_ids')
    def _onchange_price_subtotal(self):
        self._compute_amount()

    def _get_price_total_and_subtotal(self, price_unit=None, quantity=None, discount=None, currency=None, product=None,
                                      partner=None, taxes=None, move_type=None):
        self.ensure_one()
        return self._get_price_total_and_subtotal_model(
            price_unit=price_unit or self.price_unit,
            quantity=quantity or self.price_qty,
            discount=discount or self.discount,
            currency=currency or self.currency_id,
            product=product or self.product_id,
            partner=partner or self.partner_id,
            taxes=taxes or self.tax_ids,
            move_type=move_type or self.move_id.move_type,
        )

    @api.model
    def _get_fields_onchange_balance_model(self, quantity, discount, amount_currency, move_type, currency, taxes,
                                           price_subtotal, force_computation=False):
        if self.product_id:
            return {}
        else:
            return super()._get_fields_onchange_balance_model(
                quantity, discount, amount_currency, move_type, currency, taxes,
                price_subtotal, force_computation=force_computation)


