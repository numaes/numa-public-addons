### Estrategia de Implementación Polimórfica (Odoo 18)

La implementación actual de `numa_poly` ha evolucionado hacia una arquitectura de **Aplanamiento de Campos de un Solo Nivel** (Single-level Flattening) basada en `PolyReference`, abandonando la antigua lógica de "Deep Fix" y sincronización agresiva.

#### 1. Aislamiento Estricto y Detección
Un modelo se considera polimórfico **exclusivamente** si contiene el atributo `_depend_models` en su jerarquía de clases (MRO).
- **Aislamiento:** Se bloquea explícitamente la intervención en modelos core de Odoo (`res.*`, `ir.*`, `base.*`, `mail.*`, etc.) para garantizar que el ORM estándar opere sin interferencias.
- **Función Clave:** `_poly_is_polymorphic(model)` realiza esta validación de forma rápida y segura.

#### 2. Aplanamiento de Campos (Flattening)
En lugar de permitir rutas `related` profundas o recursivas, `numa_poly` resuelve el origen absoluto de cada campo durante la fase de construcción de atributos (`_build_dependant_model_attributes`).
- **Resolución Recursiva:** Si un campo proviene de una base que a su vez es polimórfica, el sistema rastrea hacia atrás hasta encontrar el modelo raíz que efectivamente guarda el campo.
- **Enlace Directo (`PolyReference`):** Si no existe un camino directo entre el modelo consumidor y la base final, el sistema inyecta automáticamente un campo `PolyReference` (Many2one técnico) que sirve como puente de un solo nivel.
- **Campos Related de 1 Salto:** Todos los campos polimórficos heredados se definen como `related` apuntando directamente a través del puente al campo original (ej. `poly_bridge_id.field_name`).

#### 3. Ciclo de Vida del Registro (Registry)
La configuración se realiza en fases controladas dentro de `setup_models`:
- **Fase 1 (Inyección Pre-Odoo):** Se preparan los puentes y se inyectan los descriptores de campos `related` antes de que el ORM de Odoo realice su propia validación de campos relacionados. Esto evita errores de "Field does not exist".
- **Fase 2 (Sincronización):** Se asegura que los atributos relacionales (`comodel_name`, `selection`, `inverse_name`) se preserven íntegramente durante la clonación de descriptores, consultando el pool global si es necesario.
- **Fase 3 (Validación Diferida):** La validación de vistas se pospone hasta que el registro está completamente estabilizado para evitar errores de campos desconocidos durante la actualización incremental de módulos.

#### 4. Robustez y Seguridad
- **Recursion Guard:** Se implementaron protecciones en descriptores de campos (especialmente en `Selection`) para evitar la evaluación prematura de lambdas durante el arranque.
- **Persistencia de Inyección:** Los campos inyectados se registran en `_fields` y `_field_definitions` de la clase, marcados como `_poly_injected` para facilitar el diagnóstico y asegurar que el ORM los reconozca como parte integral del modelo.
- **Sin Rutas Destructivas:** Se eliminó cualquier uso de `delattr` o borrado de campos en tiempo de ejecución para prevenir la corrupción del estado del servidor.
