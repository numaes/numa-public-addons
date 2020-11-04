# -*- coding: utf-8 -*-

from odoo import exceptions, _
from odoo import models, fields, api
import requests
from lxml import etree
import datetime

import logging

_logger = logging.getLogger(__name__)

BNA_URL = 'https://www.bna.com.ar'


def get_url(url):
    """Return a string of a get url query"""
    try:
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; U; Linux i686) Gecko/20071127 Firefox/2.0.0.11'
        })
        return response.text
    except IOError:
        raise exceptions.AccessError(
            _('Error: Web Service [%s] does not exist or it is non accesible !') % url
        )


class BNACurrencyData(models.Model):
    _name = 'account.currency.bna.currency'
    _description = 'BNA Currency data'
    _order = 'name'

    name = fields.Char('Nombre en BNA', required=True)
    currency_id = fields.Many2one('res.currency', 'Odoo currency', required=True)
    bna_units = fields.Integer('Unidades en cotización BNA', default=1, required=True)


class BNACurrencyUpdater(models.Model):
    _name = 'account.currency.bna.updater'
    _description = 'BNA Currency Updater'
    _order = 'name'

    def synch(self):
        currency_rate_model = self.env['res.currency.rate']
        bna_currency_model = self.env['account.currency.bna.currency']

        _logger.debug("BNA currency rate update service: connecting...")

        data = get_url(BNA_URL)
        if not data:
            _logger.error('No data could be retrieved from BNA! Please check connection!')
            raise exceptions.AccessError(
                _('Error retrieving info from BNA. No data retrieved from %s') % BNA_URL
            )

        values = {}

        page = etree.HTML(data)

        divisas = page.find(".//div[@id='divisas']")

        if not divisas:
            _logger.error('No "divisas" found! Bad site structure! Please check connection!')
            raise exceptions.AccessError(
                _('No "divisas" found! Bad site structure! Please check connection!')
            )

        fechaCot = divisas.find(".//th[@class='fechaCot']")

        dateStrParsed = fechaCot.text.split('/')

        rate_date = datetime.date(int(dateStrParsed[2]), int(dateStrParsed[1]), int(dateStrParsed[0]))

        def get_rates_from_table(tipo_moneda, rows):
            for line in rows:
                rows = line.findall("./td")
                moneda_leida = rows[0].text
                compra = float(rows[1].text)
                venta = float(rows[2].text)
                if moneda not in values:
                    values[moneda_leida] = {'fecha': rate_date}

                values[moneda_leida]['%s_compra' % tipo_moneda] = compra
                values[moneda_leida]['%s_venta' % tipo_moneda] = venta

        get_rates_from_table('billete', divisas.iterfind(".//tbody/tr"))

        billetes = page.find(".//div[@id='billetes']")

        if not billetes:
            _logger.error('No "billetes" found! Bad site structure! Please check connection!')
            raise exceptions.AccessError(
                _('No "billetes" found! Bad site structure! Please check connection!')
            )

        fechaCot = divisas.find(".//th[@class='fechaCot']")

        dateStrParsed = fechaCot.text.split('/')

        rate_date = datetime.date(int(dateStrParsed[2]), int(dateStrParsed[1]), int(dateStrParsed[0]))

        get_rates_from_table('billete', billetes.iterfind(".//tbody/tr"))

        for moneda, data in {}.items():
            bna_currency = bna_currency_model.search([('name', '=', moneda)], limit=1)
            if not bna_currency:
                _logger.error('Currency %s not found in the system! Programming error!' % moneda)
                raise exceptions.AccessError(
                    _('Currency %s not found in the system! Programming error!') % moneda
                )

            # Skip if not active
            if not bna_currency.currency_id.active:
                continue

            currency_rate = currency_rate_model.search([('currency_id', '=', bna_currency.currency_id.id),
                                                        ('date', '=', moneda['fecha'])], limit=1)
            if currency_rate:
                _logger.debug('Currency %s, rate for %s already captured! Ignoring rate' %
                              (moneda, moneda['fecha']))
                continue

            _logger.debug('Updating currency "%s" with BNA values (fecha: %s, divisa: %f, %f, billete: %f, %f)' %
                          (moneda, data['fecha'],
                           data['divisa_compra'], data['divisa_venta'],
                           data['billete_compra'], data['billete_venta']))

            bna_currency.currency_id.rate_ids = [(0, 0, {
                'name': moneda['fecha'],
                'rate': (moneda['billete_compra'] / moneda['billete_venta']) / 2,
                'bna_billete_compra': moneda.get('billete_compra', 0.0) / bna_currency.bna_units,
                'bna_billete_venta': moneda.get('billete_venta', 0.0) / bna_currency.bna_units,
                'bna_divisa_compra': moneda.get('divisa_compra', 0.0) / bna_currency.bna_units,
                'bna_divisa_venta': moneda.get('divisa_venta', 0.0) / bna_currency.bna_units,
            })]


class CurrencyConfigurationCompany(models.Model):
    _inherit = "res.company"

    bna_tipo_cotizacion = fields.Selection(
        [
            ('billete', 'Billete'),
            ('divisa', 'Divisa')
        ],
        'Tipo Cotizacion', default='billete'
    )
    bna_valor_moneda = fields.Selection(
        [
            ('compra', 'Compra'),
            ('venta', 'Venta'),
            ('promedio', 'Promedio Compra-Venta')
        ],
        'Valor Moneda', default='venta'
    )


class CurrencyRate(models.Model):
    _inherit = "res.currency.rate"

    bna_billete_compra = fields.Float('BNA Billete compra')
    bna_billete_venta = fields.Float('BNA Billete venta')
    bna_divisa_compra = fields.Float('BNA Divisa compra')
    bna_divisa_venta = fields.Float('BNA Divisa venta')
    bna_read_date = fields.Float('Fecha de lectura')


class Currency(models.Model):
    _inherit = "res.currency"

    def get_rate_records(self, company, date):
        currency_rate_model = self.env['res.currency.rate']

        if not self.ids:
            return {}
        self.env['res.currency.rate'].flush(['rate', 'currency_id', 'company_id', 'name',
                                             'bna_billete_compra', 'bna_billete_venta',
                                             'bna_divisa_compra', 'bna_divisa_compra',
                                             'bna_read_date'])

        query = """SELECT c.id,
                          COALESCE((SELECT c.id as currency_id, r.id as currency_rate_id FROM res_currency_rate r
                                  WHERE r.currency_id = c.id AND r.name <= %s
                                    AND (r.company_id IS NULL OR r.company_id = %s)
                               ORDER BY r.company_id, r.name DESC
                                  LIMIT 1), 1.0) AS rate
                   FROM res_currency c
                   WHERE c.id IN %s"""
        self._cr.execute(query, (date, company.id, tuple(self.ids)))
        currency_rates = dict(self._cr.fetchall())
        res = {}
        for currency_rate in currency_rates:
            res[currency_rate['currency_id']] = currency_rate_model.browse(currency_rate['currency_rate_id'])
        return res

    @api.model
    def _get_conversion_rate(self, from_currency, to_currency, company, date):
        currency_rates = (from_currency + to_currency).get_rate_records(company, date)

        from_rate = currency_rates[from_currency.id]
        to_rate = currency_rates[to_currency.id]

        if company.bna_tipo_cotizacion and not company.bna.valor_moneda:
            raise exceptions.UserError(
                _('No se ha configurado en la compañía el tipo de cotización a utilizar! Por favor revisar')
            )

        if company.bna_tipo_cotizacion and company.bna.valor_moneda not in ['compra', 'venta', 'promedio']:
            raise exceptions.UserError(
                _('Not considered value for bna_valor_moneda: %s! Por favor revisar') %
                company.bna_valor_moneda
            )

        if company.bna_tipo_cotizacion == 'billete':
            if company.bna_valor_moneda == 'compra':
                from_ratio = from_rate.bna_billete_compra
                to_ratio = to_rate.bna_billete_compra
            elif company.bna_valor_moneda == 'venta':
                from_ratio = from_rate.bna_billete_venta
                to_ratio = to_rate.bna_billete_venta
            else:
                from_ratio = (from_rate.bna_billete_compra + from_rate.bna_billete_venta) / 2
                to_ratio = (to_rate.bna_billete_compra + to_rate.bna_billete_venta) / 2
        elif company.bna_tipo_cotizacion == 'divisa':
            if company.bna_valor_moneda == 'compra':
                from_ratio = from_rate.bna_divisa_compra
                to_ratio = to_rate.bna_divisa_compra
            elif company.bna_valor_moneda == 'venta':
                from_ratio = from_rate.bna_divisa_venta
                to_ratio = to_rate.bna_divisa_venta
            else:
                from_ratio = (from_rate.bna_divisa_compra + from_rate.bna_divisa_venta) / 2
                to_ratio = (to_rate.bna_divisa_compra + to_rate.bna_divisa_venta) / 2
        else:
            from_ratio = (from_rate.bna_billete_compra + from_rate.bna_billete_venta) / 2
            to_ratio = (to_rate.bna_billete_compra + to_rate.bna_billete_venta) / 2

        return from_ratio / to_ratio
