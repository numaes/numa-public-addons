from odoo import fields, models, api
from odoo.tools.translate import _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
import base64
import zipfile
import StringIO
import re

import logging

_logger = logging.getLogger(__name__)


class ProductProductExtended(models.Model):
    _inherit = 'product.template'

    bien_uso_posible = fields.Boolean(u'Bien de Uso?')
    bien_uso_default = fields.Boolean(u'Default Bien de Uso')
    bien_uso_supplier_posible = fields.Boolean(u'Bien de Uso?')
    bien_uso_supplier_default = fields.Boolean(u'Default Bien de Uso')