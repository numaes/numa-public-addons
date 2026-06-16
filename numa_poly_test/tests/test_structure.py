import logging
from collections import OrderedDict

from odoo import models, fields
from odoo import api
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
from odoo.tests import Form, tagged, TransactionCase, BaseCase
from .common import PolyTestCommon

_logger = logging.getLogger(__name__)

@tagged('post_install', '-at_install')
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
        # t4_1.a1 fue reescrito a 'D1' mas arriba (linea ~68); buscamos por el valor ACTUAL.
        # (Antes buscaba 'C1' -> inconsistente con su propio write: el test estaba mal, no el
        # search. Verificado: el write del diamante persiste a test.test1 y el search anda.)
        assert t4_1 == t4_model.search([('a1', '=', 'D1')])

        # is normal path working?
        first_partner_id = self.env['res.partner'].search([], limit=1)
        t4_1.partner_id = first_partner_id

        assert t4_1 == t4_model.search([('partner_id.name', '=', first_partner_id.name)])

        # test path search using polymorphic links

        assert t4_1 == t4_model.search([('a3', '=', 'D3')])
        # a3 esta "sobrecargado" en test4 pero es el mismo campo delegado que test2_id.a3
        # (estilo _inherits) -> comparten valor. Tras reescribir a3 a 'D3', buscar por el valor
        # VIEJO 'C3' via el link no encuentra nada; por el valor ACTUAL 'D3' si encuentra.
        # (El assert original `== search('C3')` contradecia su propio comentario "should fail".)
        assert not t4_model.search([('test2_id.a3', '=', 'C3')])
        assert t4_1 == t4_model.search([('test2_id.a3', '=', 'D3')])

        t1_1.set_a1()
        assert t1_1.a1 == 'Set by test1'

        t2_1.set_a1()
        assert t2_1.a1 == 'Set by test1'

        t4_1.set_a1()
        assert t4_1.a1 == 'Set by test4'

        _logger.info(f'Ending successfully poly tests')

    def test_bulk_create(self):
        """Test creating multiple records at once."""
        _logger.info(f'Starting bulk create tests')
        t1_model = self.env['test.test1']
        t2_model = self.env['test.test2']
        t3_model = self.env['test.test3']
        t4_model = self.env['test.test4']

        # Clean up existing records
        t1_model.search([]).unlink()
        t2_model.search([]).unlink()
        t3_model.search([]).unlink()
        t4_model.search([]).unlink()

        # Create multiple records at once
        t1_records = t1_model.create([
            {'a1': 'Bulk1', 'a2': 'Bulk2'},
            {'a1': 'Bulk3', 'a2': 'Bulk4'},
            {'a1': 'Bulk5', 'a2': 'Bulk6'},
        ])

        # Verify the records were created correctly
        self.assertEqual(len(t1_records), 3)
        self.assertEqual(t1_records[0].a1, 'Bulk1')
        self.assertEqual(t1_records[0].a2, 'Bulk2')
        self.assertEqual(t1_records[1].a1, 'Bulk3')
        self.assertEqual(t1_records[1].a2, 'Bulk4')
        self.assertEqual(t1_records[2].a1, 'Bulk5')
        self.assertEqual(t1_records[2].a2, 'Bulk6')

        # Create multiple records with inheritance
        t2_records = t2_model.create([
            {'a1': 'T2Bulk1', 'a2': 'T2Bulk2', 'a3': 'T2Bulk3'},
            {'a1': 'T2Bulk4', 'a2': 'T2Bulk5', 'a3': 'T2Bulk6'},
        ])

        # Verify the records were created correctly
        self.assertEqual(len(t2_records), 2)
        self.assertEqual(t2_records[0].a1, 'T2Bulk1')
        self.assertEqual(t2_records[0].a2, 'T2Bulk2')
        self.assertEqual(t2_records[0].a3, 'T2Bulk3')
        self.assertEqual(t2_records[0].test1_id.id, t2_records[0].id)
        self.assertEqual(t2_records[0]._name, 'test.test2')
        self.assertEqual(t2_records[0].test1_id._name, 'test.test1')

        self.assertEqual(t2_records[1].a1, 'T2Bulk4')
        self.assertEqual(t2_records[1].a2, 'T2Bulk5')
        self.assertEqual(t2_records[1].a3, 'T2Bulk6')
        self.assertEqual(t2_records[1].test1_id.id, t2_records[1].id)

        # Create records with multi-inheritance
        t4_records = t4_model.create([
            {'a1': 'T4Bulk1', 'a2': 'T4Bulk2', 'a3': 'T4Bulk3', 'a4': 'T4Bulk4'},
            {'a1': 'T4Bulk5', 'a2': 'T4Bulk6', 'a3': 'T4Bulk7', 'a4': 'T4Bulk8'},
        ])

        # Verify the records were created correctly
        self.assertEqual(len(t4_records), 2)
        self.assertEqual(t4_records[0].a1, 'T4Bulk1')
        self.assertEqual(t4_records[0].a2, 'T4Bulk2')
        self.assertEqual(t4_records[0].a3, 'T4Bulk3')
        self.assertEqual(t4_records[0].a4, 'T4Bulk4')
        self.assertEqual(t4_records[0].test2_id.id, t4_records[0].id)
        self.assertEqual(t4_records[0].test3_id.id, t4_records[0].id)
        self.assertEqual(t4_records[0]._name, 'test.test4')
        self.assertEqual(t4_records[0].test2_id._name, 'test.test2')
        self.assertEqual(t4_records[0].test3_id._name, 'test.test3')

        self.assertEqual(t4_records[1].a1, 'T4Bulk5')
        self.assertEqual(t4_records[1].a2, 'T4Bulk6')
        self.assertEqual(t4_records[1].a3, 'T4Bulk7')
        self.assertEqual(t4_records[1].a4, 'T4Bulk8')

        _logger.info(f'Ending successfully bulk create tests')

    def test_bulk_write(self):
        """Test writing to multiple records at once."""
        _logger.info(f'Starting bulk write tests')
        t1_model = self.env['test.test1']
        t2_model = self.env['test.test2']
        t3_model = self.env['test.test3']
        t4_model = self.env['test.test4']

        # Clean up existing records
        t1_model.search([]).unlink()
        t2_model.search([]).unlink()
        t3_model.search([]).unlink()
        t4_model.search([]).unlink()

        # Create records for testing
        t1_records = t1_model.create([
            {'a1': 'Write1', 'a2': 'Write2'},
            {'a1': 'Write3', 'a2': 'Write4'},
            {'a1': 'Write5', 'a2': 'Write6'},
        ])

        # Write to multiple records at once
        t1_records.write({'a1': 'WrittenAll'})

        # Verify the write was applied to all records
        for record in t1_records:
            self.assertEqual(record.a1, 'WrittenAll')

        # Create records with inheritance
        t2_records = t2_model.create([
            {'a1': 'T2Write1', 'a2': 'T2Write2', 'a3': 'T2Write3'},
            {'a1': 'T2Write4', 'a2': 'T2Write5', 'a3': 'T2Write6'},
        ])

        # Write to multiple records with inheritance
        t2_records.write({
            'a1': 'T2WrittenAll',
            'a2': 'T2WrittenAll2',
            'a3': 'T2WrittenAll3'
        })

        # Verify the write was applied to all records
        for record in t2_records:
            self.assertEqual(record.a1, 'T2WrittenAll')
            self.assertEqual(record.a2, 'T2WrittenAll2')
            self.assertEqual(record.a3, 'T2WrittenAll3')
            self.assertEqual(record.test1_id.id, record.id)
            self.assertEqual(record._name, 'test.test2')
            self.assertEqual(record.test1_id._name, 'test.test1')

        # Create records with multi-inheritance
        t4_records = t4_model.create([
            {'a1': 'T4Write1', 'a2': 'T4Write2', 'a3': 'T4Write3', 'a4': 'T4Write4'},
            {'a1': 'T4Write5', 'a2': 'T4Write6', 'a3': 'T4Write7', 'a4': 'T4Write8'},
        ])

        # Write to multiple records with multi-inheritance
        t4_records.write({
            'a1': 'T4WrittenAll',
            'a2': 'T4WrittenAll2',
            'a3': 'T4WrittenAll3',
            'a4': 'T4WrittenAll4'
        })

        # Verify the write was applied to all records
        for record in t4_records:
            self.assertEqual(record.a1, 'T4WrittenAll')
            self.assertEqual(record.a2, 'T4WrittenAll2')
            self.assertEqual(record.a3, 'T4WrittenAll3')
            self.assertEqual(record.a4, 'T4WrittenAll4')
            self.assertEqual(record.test2_id.id, record.id)
            self.assertEqual(record.test3_id.id, record.id)
            self.assertEqual(record._name, 'test.test4')
            self.assertEqual(record.test2_id._name, 'test.test2')
            self.assertEqual(record.test3_id._name, 'test.test3')

        _logger.info(f'Ending successfully bulk write tests')
