# numa_poly — Notas de limpieza (hardcodes de estabilización)

> **Contexto.** La estabilización de numa_poly fue dramática y con mucho código generado por
> agentes. Quedaron **nombres de modelos/campos de consumidores hardcodeados** dentro del
> motor genérico, que en su momento taparon crashes intermedios pero son **conceptualmente
> incorrectos**: una librería genérica de polimorfismo no debe conocer a sus clientes.
>
> **Principio.** Ningún nombre de modelo/campo de un consumidor (`project.task`,
> `conversation.driver`, `driver_id`, `provider`, `pln_root_id`, `numa.planning.*`, …) debería
> aparecer en `poly.py`. Lo genérico se resuelve por **forma** (tipo de campo, self-referencia,
> link de `_depend_models`), no por **nombre**.
>
> **Método de remoción (importante).** NO remover a ciegas: cada hardcode tapó un crash real.
> Secuencia segura: (1) suite de tests verde — ya resucitada (`PolyTestCommon` + `test_structure`
> recableados, antes estaban apagados); (2) agregar el test genérico que cubre el *patrón* que el
> hardcode caso-especial; (3) remover/generalizar UN hardcode; (4) re-correr la suite. Repetir.

---

## ✅ A + B REMOVIDOS (jun-2026) — numa_planning sin instancia en producción

El dueño confirmó que **numa_planning no está en ninguna producción**, así que se removió TODO
lo de numa_planning + project.task (categorías A y B), que además estaban **auto-guardadas**
(`if 'pln_root_id' in self._fields`, `if self._name == 'project.task'`) → eran no-op para
cualquier otro consumidor. Removido: captura/cleanup de `pln_root_id` en `_migrate_to_poly`,
el bulk-update y el A2 de `_update_foreign_keys`, el skip de `project.task` (user_ids/
personal_stage), C2 (`project_task_user_rel`), C3 (`numa_planning_link`), el `f.startswith('pln_')`
en el split de campos, el intercept de log de `pln_required_resource_ids`, y el loop de re-sync
post-migración (`_pln_*`, que corría siempre bajo `is_migration=True` → nunca ejecutaba). El
manejo de M2O hacia las bases quedó **genérico** (por forma, sin nombres). **Pendiente:** correr
la suite resucitada para confirmar verde. **C (conversation.driver) NO se tocó** (otro consumidor,
puede estar en producción).

---

## A. `pln_root_id` — numa_planning incrustado en la migración genérica (la fuga mayor)

`pln_root_id` (campo de árbol self-referencial de `numa_planning`) aparece hardcodeado en todo
`_migrate_to_poly` / `_update_foreign_keys`:

- `poly.py:1726, 1780-1781, 1807-1812, 1880-1882, 1916-1944, 1970-1972, 1994, 2070-2079`.

**Problema conceptual.** El motor de migración nombra un campo de UN consumidor. Lo que
`pln_root_id` necesita —repuntar un **M2one self-referencial** al nuevo id tras la migración— es
un patrón **genérico**: cualquier m2o que apunte al propio modelo (o a un modelo de la jerarquía)
debe repuntarse igual.

**Fix genérico.** Ya existe un camino genérico embrionario (`extra_cols` junta los m2o que apuntan
a `_depend_models`, `poly.py:1808-1813`). Generalizarlo para cubrir **m2o self-referenciales**
(comodel == `self._name`) y eliminar todas las ramas `pln_root_id`. El bulk-update de
`pln_root_id` (1916-1944, 2070-2079) se reemplaza por un loop sobre *todos* los m2o
self-referenciales/intra-jerarquía descubiertos por forma.

**Test guarda.** Modelo fixture con un `parent_id = Many2one(self)` self-referencial + datos
legacy; tras `_migrate_to_poly`, `parent_id` apunta al nuevo id. Si pasa sin tocar `pln_root_id`,
las ramas hardcodeadas son removibles.

## B. `project.task` — skips por NOT NULL / campos específicos

- `poly.py:1796-1797` (`user_ids`, `personal_stage_type_ids` saltados en migración),
  `2141`, `5145-5146` (`pln_required_resource_ids`), `5905`.

**Problema.** Caso-especial para evitar violaciones NOT NULL de un consumidor.

**Fix genérico.** En vez de nombrar `project.task`, manejar genéricamente: (a) saltar M2M/O2M en
el `create` de migración y re-aplicarlos después (ya se hace para x2m en general), o (b) capturar
la violación NOT NULL y degradar, o (c) un hook declarativo `_poly_migration_skip_fields()` que el
consumidor override. La opción (c) saca el nombre del core y se lo da al dueño del modelo.

**Test guarda.** Fixture con un m2m requerido; migrar y verificar que no rompe.

## C. `conversation.driver` / `driver_id` / `provider` / `facebook_account_id`

- `poly.py:3707-3709` (hard-filter de `driver_id`), `3740` (`provider` en critical_f),
  `3874` (`provider`/`facebook_account_id`/`driver_id`), `3920`, `1315`/`4014`/`4968-4969` (comentarios).

**Problema.** Especificidades del motor de conversaciones en el `create`/related-handling genérico.

**Fix genérico.** `driver_id` es simplemente un **link field de `_depend_models`** → ya está en
`poly_links`; el hard-filter por nombre (`!= 'conversation.driver'`) es redundante con el manejo
genérico de links y debería salir. Los "critical fields" hardcodeados (`name`, `provider`,
`active`, `company_id`, `facebook_account_id`) deberían derivarse por forma (campos propios del
modelo no-related) o declararse vía hook, no por lista fija con nombres de un consumidor.

**Test guarda.** Fixture con link field nombrado distinto a `driver_id` + un campo propio "crítico":
verificar que el create preserva el campo propio sin necesitar la lista hardcodeada.

## D. Modelos core de Odoo (`res.users`/`res.groups`/`res.company`/`ir.model.data`/`ir.model`)

- `poly.py:1271, 3563, 4057, 4288, 4370, 4979, 5648` — guards dispersos con **listas literales
  que NO coinciden entre sí** (algunas incluyen `ir.model`, otras `res.company`, etc.).

**Problema.** No es "fuga de consumidor" (son core), pero las listas ad-hoc divergentes son frágiles
y difíciles de razonar.

**Fix (bajo riesgo, refactor puro).** Consolidar en **una** constante de módulo, ej.
`POLY_EXEMPT_CORE_MODELS = frozenset({...})`, y referenciarla en todos los puntos. ⚠️ Unificar las
listas cambia comportamiento sutil donde divergían — hacerlo con la suite verde y revisando cada
sitio. Es el cambio más seguro para empezar a practicar el loop test-guiado.

---

## Orden sugerido

1. ✅ Resucitar la suite (hecho: `PolyTestCommon`, `test_structure` recableado). **Correr y ver
   qué queda en verde** — algo puede haber quedado roto de la estabilización.
2. **D** primero (refactor puro, sin nombres de consumidor) para calibrar el loop.
3. **C** (`driver_id`/critical fields) — el hard-filter redundante es el más fácil de los conceptuales.
4. **A** (`pln_root_id` → m2o self-referencial genérico) — el de mayor valor conceptual.
5. **B** (`project.task` → hook `_poly_migration_skip_fields`).

Cada paso: agregar el test del patrón, remover el hardcode, correr la suite.

---

## Hallazgos al expandir la suite de regresión (jun-2026)

Al escribir tests nuevos como red de regresión aparecieron **dos caminos no testeados que están
rotos** en el estado actual del motor. Ninguno tiene cobertura previa, por eso pasaron inadvertidos.
Se documentan acá como gaps **conocidos y rastreables** (no silenciosos); su arreglo es trabajo
con forma de feature y se decide aparte (ver memoria `numa-poly-hardening`).

### 1. Migración legacy→poly (`_migrate_to_poly` / `_check_migration_needed`) — DEAD CODE

`_auto_init` (poly.py:2118) llama a `_migrate_to_poly()` sólo si `_check_migration_needed()`.
Ese detector **nunca puede devolver True hoy**, por DOS razones independientes:

- **Guard muerto**: `_check_migration_needed` (poly.py:1639) hace
  `if not hasattr(type(self), '__depends_base_classes'): return False`. Ese atributo
  **no se setea en ningún modelo** (verificado por introspección sobre test.test2/4,
  test.poly.behavior.a/child.a: ni mangled `_BaseModel__depends_base_classes` ni sin manglear).
  Es un vestigio del path de MRO reactivo "neutralized" (poly.py:1494, set en 1534 que ya no corre;
  5573-5574 sólo actualizan `if hasattr`, nunca crean). → el guard siempre corta en False.
- **Detector con NULL-in-NOT-IN**: aún sin el guard, la query
  `SELECT id FROM <tabla> WHERE id NOT IN (SELECT old_id FROM ir_poly_base WHERE concrete_model_id=X)`
  está rota: los registros poly nativos tienen `old_id = NULL` (verificado). En SQL,
  `x NOT IN (..., NULL)` nunca evalúa TRUE → la query no devuelve filas aunque exista una fila
  legacy huérfana real. Habría que filtrar `WHERE old_id IS NOT NULL` o usar `NOT EXISTS`.

**Implicancia**: si un modelo poly se despliega con datos preexistentes (no-poly) en su tabla,
**no se auto-migran**. Relevante para el onboarding de personas/comitentes (gallo.* → poly).
**Decisión pendiente del usuario**: (a) revivir = arreglar guard (usar `_depend_models`) + arreglar
el NULL-in-NOT-IN + test que lo pruebe; o (b) confirmar muerto y remover
`_migrate_to_poly`/`_check_migration_needed`/`_update_foreign_keys` como scar.

### 2. `copy()` sobre registros poly — ROTO

`self.env['test.test4'].create({...}).copy()` falla. No hay override de `copy`/`copy_data` en poly,
así que se usa el de Odoo, que arrastra al `create` los campos internos de poly heredados/inyectados:

- Primero entra al branch de dispatch por `concrete_model_id` (poly.py:3470) que además tiene un bug:
  usa `concrete_model._name` (siempre `'ir.model'`) donde quería `concrete_model.model`
  (ej. `'test.test4'`) → terminaba haciendo `create` sobre `ir.model` con campos ajenos
  (`ValueError: Invalid field 'old_id' on model 'ir.model'`).
- Corregido ese branch, el siguiente error es `psycopg2 UndefinedColumn: no existe la columna
  "poly_base_id" en la relación "test_test2"`: `copy_data` copia `poly_base_id` (y los link fields
  `testN_id`, `concrete_model_id`, `old_id`) que son **gestionados por poly** y no deben copiarse
  verbatim (apuntan a las bases del ORIGINAL).

**Arreglo correcto (feature)**: override de `copy_data` en poly que descarte el bookkeeping/links
poly (`concrete_model_id`, `old_id`, `poly_base_id`, y los `_depend_models.values()`) dejando que
`create` regenere identidad y bases frescas; + arreglar el `._name`→`.model` del branch de dispatch;
+ test `copy()` end-to-end. No se hizo half-fix en el hot path de `create` sin cobertura completa.
