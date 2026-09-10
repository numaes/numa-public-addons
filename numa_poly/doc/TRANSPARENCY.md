# Transparencia hacia los módulos que no usan poly

numa_poly parchea el ORM de Odoo, y varios de esos parches se aplican a **todos** los modelos,
no solo a los polimórficos. Que eso sea transparente para el resto de la instalación no es
automático: depende de que poly sepa distinguir con precisión qué modelos participan de una
jerarquía, y de que lo que difiere para poder arrancar lo termine haciendo.

Esta nota fija qué toca poly en los módulos ajenos, con qué criterio decide, y qué pasó cuando
ese criterio estaba mal. Sale de una revisión del 2026-09-10 sobre una instalación real: 839
modelos, 43 polimórficos.

Lo primero que conviene saber es que **en una instalación con poly casi no hay módulos ajenos**.
Modelos estándar de Odoo quedan dentro de jerarquías polimórficas: `res.partner` y `crm.lead`
como bases, `project.task` y `mrp.workorder` como subtipos de `numa.planning.node`,
`mrp.workcenter` de `numa.planning.resource`. Todo módulo que extienda cualquiera de ellos
—account, sale, crm, mrp, project— corre en territorio poly aunque no lo use. Un defecto de poly
no se queda en poly.

## El criterio: el valor de `_depend_models`, nunca su presencia

Un modelo participa de una jerarquía si alguna clase de su MRO declara `_depend_models` con un
valor distinto de `None` (`{}` para una base, un dict de padres para un subtipo), o si es
nombrado como padre en alguna de esas declaraciones.

**La presencia del atributo no distingue a nadie.** `PolyBase` declara `_depend_models = None` y
está en el MRO de todos los modelos, así que `'_depend_models' in base.__dict__` es verdadero para
los 839. Hasta esta revisión, varios chequeos estaban escritos así y eran código muerto.

El mapa se construye al final de cada `setup_models` y queda en el registry:

```python
env.registry._poly_hierarchy_model_names   # frozenset de los modelos que participan
```

Mientras dura el setup vale `None`.

## Lecturas relacionales

poly parchea `_Relational.__get__`, `One2many.__get__` y `Many2many.read`. El atajo que debía
devolver a los modelos ajenos al camino original de Odoo usaba la presencia del atributo: nunca
delegaba, y **toda lectura relacional de cualquier modelo tomaba el camino de poly**.

Ahora decide `_poly_is_outside_hierarchy(records)`, que responde True solo con certeza:

- el registry terminó de cargar (`ready`),
- el mapa de jerarquías está construido,
- y el modelo no figura en él.

Durante el setup responde siempre False, y todos los modelos siguen tomando el camino tolerante
como antes. No es un descuido: mientras poly reescribe bases y campos, modelos que no son
polimórficos también necesitan esa tolerancia (por ejemplo, el `message_ids` de cualquier
`mail.thread` cuando su inverso todavía no está armado).

No se midió el impacto en rendimiento. El cambio es de corrección: que en runtime el código de
poly no se ejecute sobre modelos que no le corresponden.

## Validación de vistas: diferida, no omitida

Mientras se cargan módulos el MRO polimórfico puede estar incompleto, y validar una vista en ese
momento da errores falsos ("campo desconocido") para campos o botones que llegan por la jerarquía.
Por eso poly difiere la validación.

**El defecto era que diferir se había vuelto omitir.** Durante la carga, `_validate_view`
devolvía True para todas las vistas de todos los módulos, y solo se anotaban para después las
`noupdate`. Ni siquiera esas llegaban: el conjunto de pendientes era un `lazy_property`, que Odoo
guarda bajo el nombre de la *función*, y la función se llamaba `_poly_pending_views` mientras el
atributo que se leía era `_pending_poly_views`. Cada lectura creaba un conjunto nuevo y vacío.
**La validación final no validó nunca una sola vista.** Por eso tampoco se notó que llamaba a
`Registry.clear_caches()`, que no existe en Odoo 18.

Y aun con el conjunto arreglado, no se habría ejecutado: la validación final colgaba de un wrapper
de `load_module_graph`. numa_poly se importa *dentro* de esa llamada (al cargar sus módulos), así
que la invocación en curso es la original y el wrapper recién aplica a la siguiente, que en un
arranque o un `-u` no ocurre.

Y con el nombre corregido seguía perdiéndose casi todo: `Registry.setup_models` llama a
`lazy_property.reset_all()`, que borra todos los `lazy_property` del registry, y durante un `-u` hay
un `setup_models` por cada módulo actualizado. Lo anotado al cargar un módulo desaparecía al empezar
el siguiente: en una actualización de 36 módulos llegaba al final 1 vista de cientos. Por eso el
conjunto de pendientes es ahora un atributo común del registry.

Cuatro defectos encadenados, cada uno suficiente para que no se validara nada.

La consecuencia, medida en la instalación revisada: **33 vistas activas rotas, con 12 causas
raíz**, en módulos que usan poly y en módulos que no. Tres eran errores de sintaxis que Odoo
rechaza al cargar y que ningún `-u` informó:

```
invisible="state not in ['running´, 'aborted']"      alfy_sirena
readonly="state !+ 'waiting'"                          alfy_documentacion
invisible="state not in ´downloaded"                   alfy_reuters
```

Otras referenciaban campos renombrados o eliminados. La búsqueda de instancias del propio
`numa_fsm` filtraba por `state` después de renombrarlo a `fsm_state`.

Ahora:

1. Durante la carga, toda vista que llega a `_validate_view` **se anota** y pasa.
2. Con todos los módulos cargados se validan todas con el registry completo, y se reportan todas
   las fallas, no solo la primera. El disparador es el `_register_hook` de `ir.poly_base`, que
   Odoo llama una sola vez por modelo al final de la carga. Queda en el log, en nivel INFO, cuántas se validaron:

   ```
   [poly] Validando 464 vista(s) diferida(s) al terminar la carga
   [poly] Las 464 vistas diferidas validan.
   ```

   Esa línea es la evidencia de que la validación corrió. Que no aparezcan errores no alcanza:
   durante años no aparecieron porque no se validaba nada.
3. Qué pasa con una falla lo decide la opción `poly_strict_view_validation`:

| Opción | Comportamiento |
|---|---|
| sin definir | estricta si se corren tests (`--test-enable`); en un servidor normal, un ERROR por vista y un WARNING con el resumen |
| `True` | aborta la carga con un `ValidationError` que lista todas las vistas inválidas |
| `False` | nunca aborta; solo se registran |

```ini
[options]
poly_strict_view_validation = True
```

El default no aborta en producción a propósito. Una instalación con vistas rotas latentes, que
antes arrancaba, no debe dejar de hacerlo de un día para el otro por actualizar poly. Pero ahora
lo informa, y una corrida de tests sí falla. **Cuando la instalación valide limpio conviene activar
la opción en producción**: `tests/test_poly_views_valid.py` es lo que lo confirma.

### Qué detecta la validación al cargar, y qué no

Medido de punta a punta con un módulo descartable que trae dos vistas rotas, una sobre
`res.currency` y otra sobre `res.partner`, y con la actualización de los 36 módulos de la
instalación revisada:

- **Se validan todas las vistas de los módulos que se cargan**, cambie o no su XML: 464 en la
  actualización de los 36 módulos. Las dos vistas rotas se reportaron por nombre y causa, tanto al
  instalar el módulo como al actualizarlo; en modo estricto el `-u` abortó.
- **No se validan las vistas de los módulos que no se cargan en esa corrida.** Esto se deduce de
  cómo carga Odoo, no se midió: si se actualiza solo el módulo que renombra un campo, la vista de
  *otro* módulo que lo usaba no se vuelve a escribir ni a validar. Así se rompieron varias de las 33:
  el renombre de `state` a `fsm_state` en numa_fsm dejó rotas vistas de alfy_documentacion y
  alfy_synch.

Esa segunda clase la detecta `tests/test_poly_views_valid.py`, que valida todas las vistas activas.
Por eso tiene que correr en cada ronda de tests.

Una medición anterior de esta misma revisión había concluido que un `-u` no revalida las vistas sin
cambios. Era falsa: la produjo la cuarta causa descrita más arriba, que vaciaba el conjunto de
pendientes.

## Estabilización después de la carga

Terminada la carga, poly repite el setup de modelos con todos los módulos presentes. Lo hacía un
wrapper de `Registry.new`, que tenía el mismo problema que la validación de vistas: numa_poly se
importa dentro de `Registry.new`, así que en el primer arranque de cada proceso —cada worker— el
wrapper no aplicaba y la estabilización no corría nunca, solo en recargas posteriores. Cuando
corría, además, lo hacía después de que `new` soltara el lock del registry, y dejaba
`registry_invalidated` en True, con lo que la siguiente señal hacía recargar a los demás workers.

Ahora cuelga de `Registry.signal_changes`, que `Registry.new` llama al final: con la carga
terminada, todavía bajo el lock, y también en el primer arranque. Corre una vez por registry,
restaura `registry_invalidated` y deja en el log cuánto tardó:

```
[poly] Registry estabilizado después de la carga en 0.29s
```

Ese tiempo es lo que se agrega a cada arranque de cada worker, que antes no se pagaba. Medido en la
instalación revisada: 0,29 a 0,36 s, sobre cargas de 4 s (arranque) y 70 s (actualización de 36
módulos).

## `_inherits` con el campo de enlace sin declarar

Odoo 18 **no crea** el campo de enlace de un `_inherits`: su `_add_field` rechaza campos que no
están declarados en la clase Python, y el registry no carga. poly reemplaza `_inherits_check` y,
cuando el campo no aparece, descarta esa entrada del `_inherits`.

Para un modelo polimórfico eso es lo esperado: el enlace lo inyecta después
`_build_poly_fields`. Para un modelo común, en cambio, descartarlo es lo único que permite
arrancar, pero **esconde un defecto del módulo**, y lo escondía en silencio. Así
`alfy.reuters.chat` perdió su delegación en `alfy.event` y con ella todos sus campos
(`comitentes`, `timestamp`, `tle_type`): la vista era inválida y procesar un día de chats rompía.

Ahora poly descarta la entrada igual, pero deja un WARNING con el modelo, el padre y el campo. El
arreglo siempre está en el módulo: declarar el enlace.

```python
event = fields.Many2one('alfy.event', required=True, ondelete='cascade')
```

## Tablas Many2many compartidas

Odoo rechaza dos campos que usan la misma tabla con las mismas columnas. poly lo tolera entre
modelos de una misma jerarquía, porque comparten id. El chequeo sumaba el `_name` de `PolyBase`
—que es `None`— a los dos conjuntos que compara: la intersección `{None}` nunca era vacía y se
toleraba **cualquier** colisión, poly o no.

Ahora el criterio es `_poly_hierarchy_names`. En la instalación revisada no había ninguna
colisión real tapada (se verificó con la regla exacta de `Many2many.setup_nonrelated`), así que el
cambio no afecta ningún arranque actual. Una colisión futura en un módulo que no usa poly se va a
rechazar como lo haría Odoo.

## Cómo auditar una instalación

- `tests/test_poly_views_valid.py` valida todas las vistas activas con el registry completo y
  lista cada falla con su causa. Si falla, lo que está roto es la vista que nombra, no poly.
- Para una revisión puntual, con el registry cargado:

  ```python
  for v in env['ir.ui.view'].search([]):
      try:
          v._check_xml()
      except Exception as e:
          print(v.get_external_id().get(v.id), v.model, str(e).strip().splitlines()[-1])
  ```

- Después de un `-u`, buscar en el log `[poly] Validando` y `vistas diferidas validan`: si no
  están, la validación final no corrió.
- Qué modelos considera poly polimórficos: `env.registry._poly_hierarchy_model_names`.

## Tests

- `numa_poly/tests/test_poly_transparency.py`: el criterio, el mapa, las condiciones del atajo y su
  reconstrucción cuando el registry se rearma en caliente.
- `numa_poly/tests/test_poly_view_validation.py`: diferir sin olvidar, validación final estricta y
  permisiva, y la opción.
- `numa_poly/tests/test_poly_views_valid.py`: la guardia sobre todas las vistas.
- `numa_poly_test/tests/test_transparency.py`: lo mismo con modelos polimórficos reales, más el
  `_inherits` común (declarado, intacto; sin declarar, descartado con aviso) y el criterio de las
  tablas Many2many.
