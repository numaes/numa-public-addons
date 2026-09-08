# El espacio de ids compartido

Un registro polimórfico y sus componentes **comparten un id**. `purchase.order.line` 1234
y su `numa.planning.node` 1234 son el mismo registro visto por dos caras. Eso convierte a
todas las tablas de una jerarquía en un único espacio de ids: si dos de ellas entregan el
mismo número a registros distintos, no hay error, hay dos registros que se pisan.

Esta nota fija las consideraciones de ese espacio. Es la parte del diseño que más caro
salió aprender: produjo 560 colisiones en una base de producción, silenciosas durante meses.

## Un solo asignador

**Todas las tablas del espacio compartido toman su `id` de `ir_poly_base_id_seq`.** No sólo
las de los modelos polimórficos: también las de sus bases, aunque esa base reciba además
registros que no participan de ninguna jerarquía.

Se implementa apuntando el `DEFAULT` de la columna:

```sql
ALTER TABLE res_partner ALTER COLUMN id SET DEFAULT nextval('ir_poly_base_id_seq');
```

`PolyBase.init()` lo re-aplica en **cada actualización**, tabla por tabla, sin preguntar si
hace falta. Es idempotente, toca el catálogo y no reescribe la tabla. Cada modelo reclama su
propia cadena, así que no depende del orden en que se cargan los módulos, y un módulo que
vuelva polimórfico a un modelo existente queda cubierto en su propia instalación.

Antes de reclamar una tabla, la secuencia se adelanta por encima del `MAX(id)` de esa tabla
si hiciera falta. Como la secuencia sólo avanza, después de recorrerlas todas quedó por
encima del máximo de todas, sin necesidad de coordinación global.

## Por qué no alcanza con "que `create()` ponga el id"

Mientras toda alta pase por `create()` de poly —que provee el id explícito y nunca usa el
`DEFAULT`— nada choca. El problema es todo lo demás: SQL directo, cargas de datos, caminos
del ORM que insertan sin id, código de terceros. Ahí se dispara el `DEFAULT`, y si apunta a
la secuencia propia de la tabla, esa secuencia no sabe nada del espacio compartido.

Lo insidioso es que el síntoma depende de la tabla:

| tabla | su secuencia | `MAX(id)` | qué pasa en un insert por default |
|---|---|---|---|
| `res_partner` | 119 | 14.763 | clave duplicada: **falla fuerte, se ve** |
| `conversation_bot` | 0 | 0 | entrega 1, 2, 3: libres acá, **ocupados en el espacio**. No falla, corrompe |

El segundo caso es el que produjo las 560 colisiones.

## Por qué no alcanza con sincronizar

La defensa anterior era reconciliar: `_get_max_poly_id()` escaneaba el `MAX(id)` de 26
tablas y `_sync_poly_sequence()` hacía `setval` bajo un advisory lock. Eso **no puede
cerrar el agujero**: sincroniza asignadores que se vuelven a separar apenas termina. Entre
dos sincronizaciones, cualquier `DEFAULT` puede entregar un id ya usado.

Con un solo asignador el requisito *"el id debe ser mayor que el de todas las bases"*
desaparece. No hace falta "mayor que"; hace falta **"nunca entregado antes"**, que es lo que
una secuencia da gratis.

Las 140 líneas de reconciliación (`_get_max_poly_id`, `_sync_poly_sequence`,
`_sync_table_id_sequence_once`) siguen en el código como red de seguridad para bases que
todavía no corrieron la migración. Una vez que ésta pasó por todas las instalaciones, son
removibles: con el asignador único, `MAX(id)` no puede superar a la secuencia.

## Concurrencia

**No hay problema de concurrencia y no hace falta ningún bloqueo.** `nextval` es atómico y
no transaccional: dos transacciones simultáneas no pueden obtener el mismo valor. Los huecos
que deja un rollback son gratis y no significan nada.

Medido: 8 sesiones concurrentes × 250 inserts = **2000 ids, 0 duplicados, en 121 ms**
(~16.500 ids/segundo). Una secuencia compartida no es un cuello de botella: `nextval` toma
un lock liviano sobre el buffer de la secuencia, fuera de la transacción. Si alguna vez
importara, `ALTER SEQUENCE ... CACHE n` lo amortiza a cambio de huecos más grandes.

## Consumo de ids

Un asignador único hace que **cada fila creada en el espacio compartido consuma un id**, más
los que queman los rollbacks. Medido en la base de producción de referencia: 520.300 filas
vivas, ~400 filas/día en las tablas que mueven la aguja.

Aun asumiendo 1.000/día para todo el sistema, el `int4` alcanza para **unos 5.900 años**; a
cien veces ese ritmo, 59 años. **Agotar los ids no es un motivo para apurar `numa_big_id`.**
El motivo bueno es otro: convertir `int4 → int8` reescribe cada tabla y cada índice, así que
cuesta en proporción al tamaño de la base. Hacerlo mientras es chica es barato.

## Qué NO comparte el espacio

Un modelo sin relación con ninguna jerarquía polimórfica conserva su propia secuencia y no
se toca. La regla práctica, sin embargo, es incluir de más: **no se puede saber de antemano
qué modelo va a volverse polimórfico.** `res.partner` es base porque `numa_planning` lo hizo
base. Los costos son asimétricos — incluir de más cuesta huecos, incluir de menos corrompe
en silencio.

## Verificar

```python
# ninguna tabla del espacio debe tener su propia secuencia como default
env['res.partner']._poly_claim_shared_id_space()   # idempotente, re-aplica

# censo de colisiones
for name in env.registry.models:
    M = env[name]
    if getattr(M, '_poly_get_depend_models', None) and M._poly_get_depend_models():
        assert not M._poly_colliding_ids(limit=5), name
```

Ver también [TRANSITION.md](TRANSITION.md) para la reconstrucción de registros
preexistentes, y `_poly_owned_base_ids()` para la pregunta *"¿esta fila base es mía?"*.
