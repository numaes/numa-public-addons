# Filtros de fecha relativos en Odoo 18

Guía para armar un filtro de fecha que, guardado como favorito, **siga moviéndose con la fecha
de hoy** en vez de quedar congelado en el día en que se creó.

La funcionalidad es nativa de Odoo 18. Este documento existe porque no está señalizada: el
operador que hay que usar no menciona en ningún lado que sea relativo.

---

## El problema

Lo intuitivo es escribir la fecha con un atajo. En un campo de fecha, Odoo acepta expresiones
como `+2w`, `-3m`, `+10d`: se tipea y el widget completa la fecha resultante.

Eso **no** produce un filtro relativo. El atajo lo resuelve el widget de fecha en el momento de
tipear: al dominio le llega ya la fecha literal. Cuando se guarda el favorito, lo que queda
guardado es `2026-09-17`, no "dos semanas desde hoy". Una semana después el filtro sigue
apuntando al mismo día fijo y deja de servir.

Lo mismo pasa —y esto es menos obvio— con los **filtros de período de la barra de búsqueda**
("Este mes", "Trimestre anterior", "Este año"). Se ven relativos, pero no lo son: se calculan
como fechas concretas contra la fecha de referencia del momento
(`web/static/src/search/utils/dates.js`, `constructDateRange`). Guardados como favorito quedan
igual de fijos.

La relatividad no está en **cómo se escribe el valor**. Está en el **operador**.

---

## Cómo se hace

1. En la vista de lista o kanban, abrí **Filtros → Añadir filtro personalizado**.
2. Elegí el campo de fecha (por ejemplo *Fecha de creación*).
3. En el operador, elegí **`está dentro de`** (*"is within"* en inglés).
4. Aparecen dos casillas: una cantidad y una unidad. Cargá por ejemplo `-1` y `meses`.
   - **Negativo** = hacia atrás. `-1 meses` es "desde hace un mes hasta hoy".
   - **Positivo** = hacia adelante. `+7 días` es "desde hoy hasta dentro de una semana".
5. **Agregar**, y después guardalo con **Guardar búsqueda actual** y un nombre.

Con este módulo instalado, al lado de las casillas aparece un `desde hoy` con un tooltip que
recuerda que el filtro se recalcula en cada uso. Es sólo un cartel: la funcionalidad es la misma
con el módulo instalado o sin él.

El favorito queda relativo. Cada vez que se abre, se recalcula contra la fecha de ese día.

---

## Qué queda guardado, y por qué funciona

El operador `está dentro de` no genera fechas: genera un dominio hecho de **expresiones**.
Para `-1 meses` sobre un campo `date`, lo que se guarda es (formateado para leerlo):

```python
[
    "&",
    ("create_date", ">=", '(context_today() + relativedelta(months=-1)).strftime("%Y-%m-%d")'),
    ("create_date", "<=", 'context_today().strftime("%Y-%m-%d")'),
]
```

Tres piezas encajan para que eso sobreviva:

1. **El favorito se serializa sin evaluar.** Al guardar, el buscador pide el dominio en crudo:
   `this._getDomain({ raw: true, withGlobal: false }).toString()`
   (`web/static/src/search/search_model.js`). Con `raw: true` devuelve el árbol tal cual, con las
   expresiones intactas; sin ese flag las habría resuelto a fechas.
2. **`ir.filters.domain` es un campo Text**, no una estructura evaluada. Guarda la cadena.
3. **Se reevalúa en cada uso**, del lado del cliente, donde el evaluador de Python-en-JS provee
   `context_today()` y `relativedelta` (`web/static/src/core/py_js/py_builtin.js`).

Por eso el filtro se mueve solo: nunca hubo una fecha guardada.

Y el camino inverso también funciona: si después editás el filtro, Odoo reconoce esas
expresiones y te lo vuelve a mostrar como `está dentro de` con su cantidad y su unidad
(`condition_tree.js`, `createWithinOperators`). No se degrada a dominio crudo.

---

## Los tres límites

Conviene conocerlos antes de prometerle algo al usuario.

### 1. Sólo cuatro unidades

Días, semanas, meses y años. **No hay horas, minutos ni trimestres.**

Y no es cuestión de agregarlos a la lista de opciones:

- `relativedelta` no tiene un argumento `quarters`. Un trimestre habría que expresarlo como
  `months=3*n`, que la conversión actual no contempla.
- Para campos `datetime`, la expresión generada combina la fecha corrida con
  `datetime.time(0, 0, 0)` (`condition_tree.js`, `DELTA_DATETIME_AST`). O sea: la delta se aplica
  a la **fecha** y después se fuerza medianoche. Una delta de horas o minutos se descartaría sin
  aviso, y el filtro quedaría silenciosamente mal.

Cualquiera de las dos cosas obliga a duplicar lógica de conversión de core, no a tocar una lista.

### 2. Siempre un rango anclado en hoy

El operador produce `entre hoy y hoy±N`. No se puede expresar un solo extremo relativo, del
tipo "anterior a hace dos semanas" (sin techo). Para eso haría falta un operador nuevo.

### 3. El ancla es siempre hoy

No hay "primer día del mes actual" ni "cierre del trimestre pasado". El punto de partida es
`context_today()` y nada más.

---

## Nota para quien programe filtros del lado servidor

Si alguna vez se evalúa un `ir.filters` desde Python, ojo: `ir_filters._get_eval_domain` expone
solamente `datetime` y `context_today`, **no** `relativedelta`. Un dominio generado por
`está dentro de` no evalúa en ese contexto.

En la práctica no molesta, porque los filtros de búsqueda se evalúan en el cliente; ese método
sólo lo usa `website_snippet_filter`. Pero si se agrega otro consumidor server-side de filtros
guardados, hay que sumar `relativedelta` al contexto de evaluación.

---

## Archivos de core involucrados

Para cuando haya que revisar esto en una versión siguiente:

| Archivo | Qué aporta |
|---|---|
| `core/tree_editor/condition_tree.js` | `DELTA_DATE_AST` / `DELTA_DATETIME_AST`, y la conversión `within` ↔ `between` de expresiones |
| `core/tree_editor/tree_editor_components.js` | el componente `Within` y sus cuatro unidades |
| `core/tree_editor/tree_editor_operator_editor.js` | la etiqueta `is within` |
| `core/domain_selector/domain_selector_operator_editor.js` | ofrece `within` para `date`/`datetime` |
| `search/search_model.js` | guarda el favorito con `raw: true` |
| `search/utils/dates.js` | los filtros de período, que sí calculan fechas concretas |
