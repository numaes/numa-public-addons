# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class TestPolyOrmBehavior(TransactionCase):
    """
    Test suite for basic ORM behavior of polymorphic models.
    Validates creation, search, write, and deletion across hierarchies.
    """

    def test_01_single_behavior_create(self):
        """Valida que al crear un registro de test.poly.project, el registro en behavior.a se crea correctamente."""
        project = self.env['test.poly.project'].create({
            'name': 'Project Alpha',
            'field_a': 'Behavior A Value'
        })
        self.assertTrue(project.behavior_a_id, "El Many2one de comportamiento A debería haberse poblado.")
        self.assertEqual(project.behavior_a_id.id, project.id, "Los registros deben compartir el mismo ID.")
        
        behavior_a = self.env['test.poly.behavior.a'].browse(project.id)
        self.assertTrue(behavior_a.exists(), "El registro físico en behavior.a debe existir.")
        self.assertEqual(behavior_a.field_a, 'Behavior A Value', "El valor del campo inyectado no es correcto.")

    def test_02_multi_behavior_create(self):
        """Valida la creación múltiple de comportamientos con el mismo ID."""
        project = self.env['test.poly.project'].create({
            'name': 'Project Beta',
            'field_a': 'Injected A',
            'field_b': 42
        })
        self.assertEqual(project.behavior_a_id.id, project.id)
        self.assertEqual(project.behavior_b_id.id, project.id)
        
        behavior_a = self.env['test.poly.behavior.a'].browse(project.id)
        behavior_b = self.env['test.poly.behavior.b'].browse(project.id)
        
        self.assertEqual(behavior_a.field_a, 'Injected A')
        self.assertEqual(behavior_b.field_b, 42)

    def test_03_search_on_injected_field(self):
        """Prueba crítica: Búsqueda en campos inyectados."""
        Project = self.env['test.poly.project']
        Project.create({'name': 'P1', 'field_a': 'FindMe'})
        Project.create({'name': 'P2', 'field_a': 'Other'})
        Project.create({'name': 'P3', 'field_a': 'FindMe'})

        found = Project.search([('field_a', '=', 'FindMe')])
        self.assertEqual(len(found), 2, "La búsqueda en campo inyectado debería retornar 2 registros.")
        self.assertCountEqual(found.mapped('name'), ['P1', 'P3'])

    def test_04_write_on_injected_field(self):
        """Verifica que write() propaga los cambios a los modelos base."""
        project = self.env['test.poly.project'].create({'name': 'UpdateTest', 'field_a': 'OldValue'})
        project.write({'field_a': 'NewValue', 'field_b': 100})
        
        behavior_a = self.env['test.poly.behavior.a'].browse(project.id)
        behavior_b = self.env['test.poly.behavior.b'].browse(project.id)
        
        self.assertEqual(behavior_a.field_a, 'NewValue')
        self.assertEqual(behavior_b.field_b, 100)

    def test_05_unlink_cascades_correctly(self):
        """Verifica que la eliminación se propaga a todas las bases."""
        project = self.env['test.poly.project'].create({'name': 'DeleteTest', 'field_a': 'A', 'field_b': 1})
        p_id = project.id
        
        # Verificar existencia
        self.assertTrue(self.env['test.poly.behavior.a'].browse(p_id).exists())
        self.assertTrue(self.env['test.poly.behavior.b'].browse(p_id).exists())
        
        project.unlink()
        
        # Verificar eliminación
        self.assertFalse(self.env['test.poly.project'].browse(p_id).exists())
        self.assertFalse(self.env['test.poly.behavior.a'].browse(p_id).exists())
        self.assertFalse(self.env['test.poly.behavior.b'].browse(p_id).exists())
