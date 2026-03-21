### Lecciones Aprendidas: Integración de numa_poly con Odoo 18

1. **Introspección Agresiva de Odoo 18**:
   Odoo 18 clona automáticamente atributos de campos (especialmente `related`) basándose en la jerarquía de clases (MRO). Si una clase hereda de otra que es un modelo polimórfico, Odoo inyectará rutas `related` que apuntan al nombre del modelo base en lugar de al campo de enlace polimórfico (ej. `related='base.model.name.field'`).

2. **Intervención Temprana en `setup_related`**:
   Las correcciones en `_poly_registry_setup_models` a menudo ocurren demasiado tarde para Odoo 18. Es imperativo parchear `odoo.fields.Field.setup_related` para interceptar y corregir estas rutas antes de que Odoo intente validarlas y lance un `KeyError`.

3. **Mecanismos de Failsafe**:
   Dada la naturaleza incremental de la carga de Odoo, siempre es recomendable implementar un mecanismo de limpieza iterativa de rutas `related` que comiencen por nombres de modelos pero que no sean campos en el contexto actual. Esto evita crashes fatales que bloquean la inicialización de la base de datos.

4. **Persistencia de Campos Many2many**:
   Los campos Many2many polimórficos deben ser forzosamente `store=False` y `related` en los modelos hijos para evitar que Odoo intente crear tablas de relación físicas o realice JOINs a tablas inexistentes durante la lectura.

5. **Importancia de los Tests de Configuración**:
   Simular jerarquías polimórficas complejas en tests de "post_install" permite detectar estos problemas de inicialización que el ORM de Odoo oculta durante el uso normal pero que fallan durante el `update all`.
