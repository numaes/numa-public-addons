# Numa Web Relative Dates

Señaliza el filtro de fecha **relativo** que Odoo 18 ya sabe hacer, pero que nadie encuentra.

## Para qué

Un filtro de fecha guardado como favorito normalmente queda congelado: se guarda la fecha
concreta y a la semana siguiente el filtro ya no sirve. Odoo 18 tiene la solución nativa —el
operador `está dentro de` (`within`) genera un dominio con expresiones que se recalculan en cada
uso— pero no lo dice en ninguna parte: el operador no menciona que sea relativo, y la fila de
edición muestra sólo un número y una unidad (`-1  meses`).

Este módulo agrega esa información donde el usuario está mirando: un `desde hoy` al lado de las
casillas, con un tooltip que aclara que el filtro se recalcula y que guardarlo como favorito no
lo congela.

**No cambia comportamiento ni datos.** Es un texto. Sacar el módulo no rompe ningún filtro ya
guardado, porque los filtros los genera core.

## Instalación

Depende sólo de `web`. No tiene modelos, ni vistas, ni datos: un único XML de assets.

## Cómo se usa el filtro

Ver [`docs/filtros_fecha_relativa.md`](docs/filtros_fecha_relativa.md) — el paso a paso, qué
queda guardado y por qué funciona, y los tres límites de la implementación nativa (sólo días /
semanas / meses / años; el rango siempre anclado en hoy; sin un único extremo relativo).

## Lo que este módulo NO hace

No extiende las unidades disponibles. Agregar horas o trimestres **no** es agregar entradas a
`Within.options`:

- `relativedelta` no acepta `quarters`.
- En campos `datetime` la expresión generada fuerza medianoche
  (`datetime.datetime.combine(..., datetime.time(0, 0, 0))`), así que una delta de horas se
  descartaría en silencio.

Las dos cosas requieren duplicar lógica de conversión de core. Está documentado en la guía por si
alguna vez se decide encararlo.

## Pruebas

```bash
odoo-bin -d <base> -i numa_web_relative_dates --test-enable --stop-after-init
```

Las pruebas se corren contra el **bundle generado**, no contra el XML fuente. El punto frágil de
este módulo es el ancla: heredamos por nombre una plantilla de `web`, y si Odoo la renombra la
herencia se cae **sin excepción** —`generate_xml_bundle` sólo agrega un `console.error` al
bundle—, con lo cual el cartel desaparecería y nadie se enteraría. Las pruebas verifican que la
plantilla de core siga existiendo, que la extensión quede registrada contra ella y que el texto
llegue con la forma exacta que espera el `.po`.

## Licencia

AGPL-3. NUMA Extreme Systems.
