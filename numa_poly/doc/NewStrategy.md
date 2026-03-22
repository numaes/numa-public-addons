La estrategia propuesta busca estabilizar el proceso de carga de modelos polimórficos en Odoo 18, pasando de un enfoque "reactivo" (parchear mientras Odoo carga) a uno de "limpieza y validación final".

Esta estrategia se divide en 4 pasos incrementales para asegurar la estabilidad y permitir pruebas en cada etapa.

---

### Paso 1: Centralización del MRO Polimórfico (La "Etapa 2")

**Objetivo:** Eliminar la inyección de MRO durante la creación de clases (`_build_model`) y centralizarla en un único punto después de que todas las clases de Python han sido cargadas.

**Acciones:**
*   Desactivar `_poly_apply_polymorphic_hierarchy` dentro de `_build_model`.
*   Refactorizar `_poly_registry_setup_models` para que sea el único responsable de calcular e inyectar las clases base de `_depend_models` en `__bases__` usando `ctypes` para forzar la actualización del MRO en Python.
*   **Prueba:** Verificar que tras la carga, el MRO de un modelo polimórfico (ej. `project.task`) contiene las clases de sus dependencias, aunque los campos aún no estén sincronizados.

---

### Paso 2: Neutralización y Acumulación de Vistas

**Objetivo:** Evitar que Odoo intente validar vistas durante el proceso incremental de actualización (`-u`), ya que en ese momento el MRO está incompleto y faltan campos.

**Acciones:**
*   Modificar el parche de `ir.ui.view._validate_module_views`. En lugar de validar o saltar, debe acumular los IDs de las vistas en un set global en la `registry` (ej. `registry._pending_poly_views`).
*   Asegurar que `_validate_view` (la validación individual) devuelva `True` silenciosamente si estamos en modo `_init`.
*   **Prueba:** Realizar un `-u` de un módulo que extienda un modelo polimórfico. No debería haber errores de "Unknown field", pero las vistas nuevas no aparecerán validadas aún.

---

### Paso 3: Sincronización Final de Fields (La "Etapa 3")

**Objetivo:** Una vez fijado el MRO en el Paso 1, forzar a Odoo a reconocer los campos heredados polimórficamente como `related` automáticos.

**Acciones:**
*   En `_poly_registry_setup_models`, después de fijar el MRO, llamar a `_setup_base()` y `_setup_fields()` para los modelos afectados.
*   Refactorizar `_setup_base` en `PolyBase` para que detecte correctamente qué campos provienen de la jerarquía polimórfica y los trate como no-propios (sin columna en DB).
*   **Prueba:** Verificar que `self.env['modelo.polimorfico']._fields` contiene todos los campos esperados y que los campos de los "padres" están marcados como `related`.

---

### Paso 4: Orquestación y Validación Diferida

**Objetivo:** Ejecutar la validación masiva de vistas acumuladas en el Paso 2, justo antes de que Odoo finalice la carga.

**Acciones:**
*   Interceptar el final de `load_modules` (o mediante un hook en `Registry.load`).
*   Ejecutar en orden:
    1.  Inyección de MRO (Paso 1).
    2.  Setup de Fields (Paso 3).
    3.  Validación masiva: `for view in pending_views: view._check_xml()`.
*   **Prueba:** El sistema debe arrancar sin errores y todas las vistas (incluidas las polimórficas) deben estar correctamente validadas en la base de datos.

---

### Prompt para el Primer Paso (Paso 1)

> "Actúa como un experto en el core de Odoo. Necesitamos implementar la primera fase de la reestructuración de `numa_poly`.
>
> **Tarea:** Centralizar la inyección del MRO polimórfico.
>
> 1. Modifica `numa_poly/models/poly.py` para que `_build_model` ya no llame a `_apply_polymorphic_hierarchy` (o que esta función no modifique `__bases__` prematuramente).
> 2. Refactoriza `_poly_registry_setup_models` (que extiende `Registry.setup_models`) para que realice una pasada completa sobre todos los modelos de la registry.
> 3. Para cada modelo que tenga `_depend_models` (directa o indirectamente), debe calcular el orden correcto de clases base e inyectarlas en `model_class.__bases__`.
> 4. Debes usar `ctypes.pythonapi.PyType_Modified` para asegurar que Python recalcule el MRO internamente tras modificar `__bases__`.
> 5. Asegúrate de que esta lógica sea idempotente y maneje correctamente modelos que ya han sido procesados.
>
> No te preocupes por la validación de vistas o el setup de campos todavía, eso vendrá en pasos posteriores. Enfócate en que la jerarquía de clases de Python sea la correcta al finalizar `setup_models`."