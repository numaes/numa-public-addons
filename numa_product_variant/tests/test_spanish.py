# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.numa_physical_product.tests.translation_check import (
    TranslationCoverage)


@tagged('post_install', '-at_install')
class TestSpanish(TranslationCoverage, TransactionCase):
    """El castellano completo, o no esta en castellano.

    Un modulo con los errores traducidos y los campos en ingles no esta a
    medio traducir: parece traducido, que es como se queda asi.
    """

    TRANSLATED_MODULE = 'numa_product_variant'
