# Numa Big ID

## Descripción

Este módulo es una dependencia crítica de `numa_poly`. Odoo usa por defecto `int4` (Integer) para los IDs y claves foráneas, lo que limita los registros a 2.147 millones. `numa_poly` unifica secuencias, lo que agotará rápidamente este límite.

El objetivo de `numa_big_id` es convertir **toda la aritmética de enteros de la base de datos a 64 bits (`int8` / `BIGINT`)** para garantizar escalabilidad infinita.

## Características

- **Migración Pre-instalación**: Convierte automáticamente todas las columnas `integer` a `BIGINT` durante la instalación
- **Safety Check**: Verifica que las tablas críticas no excedan 500,000 registros antes de la migración
- **Monkey Patch del ORM**: Fuerza que todos los campos `Integer` se mapeen a `BIGINT` en PostgreSQL
- **Conversión de Secuencias**: Convierte todas las secuencias a `BIGINT`

## Instalación

**IMPORTANTE**: Este módulo debe instalarse **ANTES** que cualquier otro módulo que use modelos polimórficos (como `numa_poly`).

1. Agregar el módulo a la lista de addons
2. Actualizar la lista de módulos
3. Instalar `numa_big_id` primero
4. Luego instalar otros módulos que dependan de él

## Limitaciones

- **Migración Irreversible**: La migración a BIGINT no puede revertirse automáticamente
- **Bases de Datos Grandes**: Si alguna tabla crítica tiene más de 500,000 registros, la instalación se abortará y se requerirá migración manual por un DBA
- **Compatibilidad**: Compatible con Odoo 16, 17 y 18

## Uso

Una vez instalado, el módulo:

1. Migra automáticamente todas las columnas `integer` existentes a `BIGINT`
2. Parchea el ORM para que todos los nuevos campos `Integer` se creen como `BIGINT`
3. Asegura que las secuencias usen `BIGINT`

No se requiere configuración adicional después de la instalación.

## Troubleshooting

### Error: "La base de datos es demasiado grande para una migración automática segura"

Si recibe este error, significa que alguna tabla crítica tiene más de 500,000 registros. En este caso:

1. Contacte a un DBA para realizar la migración manual
2. El DBA debe ejecutar scripts SQL para convertir las columnas a BIGINT
3. Una vez completada la migración manual, puede instalar el módulo

### Verificar que la migración fue exitosa

Puede verificar que las columnas fueron convertidas ejecutando:

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
AND data_type = 'integer'
ORDER BY table_name, column_name;
```

Si la migración fue exitosa, esta consulta no debería devolver resultados (o solo columnas que no deberían ser BIGINT).

## Autor

NUMA Extreme Systems

## Licencia

AGPL-3
