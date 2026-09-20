# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class TestPolyAdvancedAPI(TransactionCase):
    """
    Advanced test suite for numa_poly.
    Validates casting to concrete models and performance optimizations (N+1).
    """

    def test_10_as_concrete_model_api(self):
        """Valida el método as_concrete_model() para navegar por la jerarquía."""
        # Crear un registro en el modelo concreto
        child_a = self.env['test.poly.child.a'].create({
            'base_field': 'Base Data',
            'child_a_field': 'Child Specific'
        })
        child_id = child_a.id
        
        # Obtenerlo desde el modelo base
        base_record = self.env['test.poly.base'].browse(child_id)
        self.assertEqual(base_record._name, 'test.poly.base')
        
        # Castear al modelo concreto
        concrete = base_record.as_concrete_model()
        self.assertEqual(concrete._name, 'test.poly.child.a')
        self.assertEqual(concrete.id, child_id)
        self.assertEqual(concrete.child_a_field, 'Child Specific')

    def test_11_performance_n_plus_one(self):
        """
        Prueba crítica de rendimiento: Verifica que no haya N+1 en campos inyectados.
        Debe usar prefetching para cargar datos de los modelos base en una sola query.
        """
        Project = self.env['test.poly.project']
        # 1. Crear 10 registros
        for i in range(10):
            Project.create({
                'name': f'Project {i}',
                'field_a': f'Value {i}'
            })
        
        # 2. Buscar todos los proyectos
        projects = Project.search([('name', 'like', 'Project %')])
        self.assertEqual(len(projects), 10)
        
        # 3. Validar contador de queries
        # El prefetch debería cargar 'field_a' para todos los registros en la
        # primera iteración, no uno por registro: eso es lo que se mide.
        #
        # Hay que vaciar la caché antes de medir. Sin esto los valores ya están
        # en memoria desde el create, la lectura no toca la base, y
        # assertQueryCount corta con "did not detect any queries": no es que el
        # prefetch ande de más, es que no se midió nada.
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            for project in projects:
                # Acceder al campo inyectado
                val = project.field_a
                self.assertTrue(val.startswith('Value '))
