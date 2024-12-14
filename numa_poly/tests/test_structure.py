import logging
from collections import OrderedDict

from odoo import models, fields
from odoo import api
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
from odoo.tests import Form, tagged, TransactionCase, BaseCase
from .common import PolyTestCommon

_logger = logging.getLogger(__name__)

class TestStructure(PolyTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context,
            test_queue_job_no_delay=True,  # no jobs thanks
        ))

    def test_structural_integrity(self):
        _logger.info(f'Starting poly tests')

        t1_model = self.env['test.test1']
        t2_model = self.env['test.test2']
        t3_model = self.env['test.test3']
        t4_model = self.env['test.test4']

        t1_model.search([]).unlink()
        t2_model.search([]).unlink()
        t3_model.search([]).unlink()
        t4_model.search([]).unlink()

        t1_1 = t1_model.create({'a1': 'A1', 'a2': 'A2'})
        assert t1_1.a1 == 'A1'
        assert t1_1.a2 == 'A2'
        t2_1 = t2_model.create({'a3': 'A3'})
        assert t2_1.a1 == False
        assert t2_1.a2 == False
        assert t2_1.a3 == 'A3'
        t3_1 = t3_model.create({'a4': 'A4'})
        assert t3_1.a1 == False
        assert t3_1.a2 == False
        assert t3_1.a4 == 'A4'

        t2_2 = t2_model.create({'a1': 'B1', 'a2': 'B2', 'a3': 'B3'})
        assert t2_2.a1 == 'B1'
        assert t2_2.a2 == 'B2'
        assert t2_2.a3 == 'B3'
        assert t2_2.test1_id.id == t2_2.id
        assert t2_2._name == 'test.test2'
        assert t2_2.test1_id._name == 'test.test1'

        t4_1 = t4_model.create({'a1': 'C1', 'a2': 'C2', 'a3': 'C3'})

        self.env.flush_all()

        assert t4_1.a1 == 'C1'
        assert t4_1.a2 == 'C2'
        assert t4_1.a3 == 'C3'
        assert t4_1.test2_id.id == t4_1.id
        assert t4_1.test3_id.id == t4_1.id
        assert t4_1._name == 'test.test4'
        assert t4_1.test2_id._name == 'test.test2'
        assert t4_1.test3_id._name == 'test.test3'

        t4_1.a1 = 'D1'
        t4_1.a2 = 'D2'
        t4_1.a3 = 'D3'

        assert t4_1.a1 == 'D1'
        assert t4_1.a2 == 'D2'
        assert t4_1.a3 == 'D3'

        t1s = t1_model.search([])
        t2s = t2_model.search([])
        t3s = t3_model.search([])
        t4s = t4_model.search([])

        assert len(t1s) == 5
        assert len(t2s) == 3
        assert len(t3s) == 2
        assert len(t4s) == 1

        poly_base_model = self.env['ir.poly_base']
        poly_base_2 = poly_base_model.browse(t4_1.id)

        assert poly_base_2._name == 'ir.poly_base'
        t4_2 = poly_base_2.as_concrete_model()
        assert t4_2._name == 'test.test4'

        # Search tests. Ensure expression is running ok
        assert t1_1 == t1_model.search([('a1', '=', 'A1')])
        assert t2_2 == t2_model.search([('a1', '=', 'B1')])
        assert t4_1 == t4_model.search([('a1', '=', 'C1')])

        # is normal path working?
        first_partner_id = self.env['res.partner'].search([], limit=1)
        t4_1.partner_id = first_partner_id

        assert t4_1 == t4_model.search([('partner_id.name', '=', first_partner_id.name)])

        # test path search using polymorphic links

        assert t4_1 == t4_model.search([('a3', '=', 'D3')])
        # The following search should fail, a3 is overloaded in test4!
        assert t4_1 == t4_model.search([('test2_id.a3', '=', 'C3')])

        t1_1.set_a1()
        assert t1_1.a1 == 'Set by test1'

        t2_1.set_a1()
        assert t2_1.a1 == 'Set by test1'

        t4_1.set_a1()
        assert t4_1.a1 == 'Set by test4'

        _logger.info(f'Ending successfully poly tests')

