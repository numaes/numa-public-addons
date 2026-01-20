# Numa Big ID

## Descripción

Este módulo es una dependencia crítica de `numa_poly`. Odoo usa por defecto `int4` (Integer) para los IDs y claves foráneas, lo que limita los registros a 2.147 millones. `numa_poly` unifica secuencias, lo que agotará rápidamente este límite.

El objetivo de `numa_big_id` es convertir **toda la aritmética de enteros de la base de datos a 64 bits (`int8` / `BIGINT`)** para garantizar escalabilidad infinita.

## Características

- **Migración Pre-instalación**: Convierte automáticamente todas las columnas `integer` a `BIGINT` durante la instalación
- **Safety Check**: Verifica que las tablas críticas no excedan 500,000 registros antes de la migración
- **Monkey Patch del ORM**: Fuerza que todos los campos `Integer` se mapeen a `BIGINT` en PostgreSQL
- **Conversión de Secuencias**: Convierte todas las secuencias a `BIGINT`
- **Manejo de Vistas**: Detecta y recrea automáticamente vistas que dependen de columnas convertidas
- **Manejo de Herencia de Tablas**: Omite columnas heredadas (no se pueden alterar directamente)
- **Manejo de Palabras Reservadas**: Escapa correctamente nombres de columnas que son palabras reservadas de PostgreSQL
- **Commits Periódicos**: Realiza commits cada 50 conversiones para evitar agotamiento de locks

## Arquitectura

### Pre-installation Hook (`hooks.py`)

El hook `pre_init_hook` se ejecuta durante la instalación del módulo y realiza:

1. **Safety Check**: Verifica que tablas críticas comunes no excedan `MAX_SAFE_ROWS` (500,000 por defecto)
2. **Migración de Columnas ID**: Convierte todas las columnas `id` de tipo `integer` a `bigint`
3. **Migración de Otras Columnas**: Convierte todas las demás columnas `integer` (FKs, campos numéricos, etc.)
4. **Migración de Secuencias**: Convierte todas las secuencias a `bigint`
5. **Verificación Final**: Verifica que las conversiones fueron exitosas

**Características del Hook:**
- Procesa **TODAS** las tablas del esquema `public`, sin depender de módulos específicos
- Maneja automáticamente vistas dependientes (las elimina temporalmente y las recrea)
- Omite tablas con herencia (las columnas heredadas se convierten en la tabla padre)
- Escapa nombres de columnas que son palabras reservadas de PostgreSQL
- Realiza commits periódicos para evitar agotamiento de locks

### Monkey Patch del ORM (`models/big_int_patch.py`)

El patch se aplica al cargar el módulo y modifica:

- `fields.Integer.column_type`: Devuelve `('int8', 'bigint')` en lugar de `('int4', 'int4')`
- `fields.Many2one.column_type`: Aplica el mismo patch para claves foráneas
- `fields.Many2many._update_relation_table`: Asegura que las tablas de relación usen `BIGINT`

**Compatibilidad:**
- Compatible con Odoo 18 (usa `lazy_property` correctamente)
- Maneja correctamente el acceso con subscript (`field.column_type[1]`)
- No interfiere con otros módulos

## Instalación

**IMPORTANTE**: Este módulo debe instalarse **ANTES** que cualquier otro módulo que use modelos polimórficos (como `numa_poly`).

1. Agregar el módulo a la lista de addons
2. Actualizar la lista de módulos
3. Instalar `numa_big_id` primero
4. Luego instalar otros módulos que dependan de él

**Nota**: El hook `pre_init_hook` solo se ejecuta durante la instalación inicial. Si el módulo ya está instalado y necesita ejecutar la migración, debe desinstalarlo y reinstalarlo.

## Configuración

El módulo tiene dos constantes configurables en `hooks.py`:

- `MAX_SAFE_ROWS = 500000`: Límite de registros en tablas críticas antes de abortar la migración
- `HANDLE_FOREIGN_KEYS = False`: Si es `True`, elimina y recrea foreign keys durante la conversión de columnas `id` (puede ser muy lento en bases medianas/grandes)

## Limitaciones

- **Migración Irreversible**: La migración a BIGINT no puede revertirse automáticamente
- **Bases de Datos Grandes**: Si alguna tabla crítica tiene más de 500,000 registros, la instalación se abortará y se requerirá migración manual por un DBA
- **Compatibilidad**: Compatible con Odoo 18 (probado), debería funcionar en 16 y 17
- **Tablas con Herencia**: Las columnas heredadas se omiten (se convierten en la tabla padre)
- **Vistas Complejas**: Algunas vistas muy complejas pueden requerir recreación manual si falla la recreación automática

## Uso

Una vez instalado, el módulo:

1. Migra automáticamente todas las columnas `integer` existentes a `BIGINT`
2. Parchea el ORM para que todos los nuevos campos `Integer` se creen como `BIGINT`
3. Asegura que las secuencias usen `BIGINT`

No se requiere configuración adicional después de la instalación.

## Generalización

Este módulo está completamente generalizado y no depende de módulos específicos:

- **Procesa todas las tablas**: No hay hardcoding de nombres de tablas específicas (excepto para el safety check)
- **Safety check genérico**: Las tablas en `CRITICAL_TABLES` son solo para estimar el tamaño de la base de datos
- **Sin dependencias de módulos**: Funciona con cualquier combinación de módulos instalados
- **Manejo automático**: Detecta y maneja automáticamente vistas, herencia, palabras reservadas, etc.

## Troubleshooting

### Error: "La base de datos es demasiado grande para una migración automática segura"

Si recibe este error, significa que alguna tabla crítica tiene más de 500,000 registros. Opciones:

1. **Ajustar el límite**: Modifique `MAX_SAFE_ROWS` en `hooks.py` si confía en que la migración funcionará
2. **Migración manual**: Contacte a un DBA para realizar la migración manual mediante scripts SQL
3. **Una vez completada la migración manual**: Puede instalar el módulo (el hook detectará que las columnas ya son BIGINT y las omitirá)

### Error: "cannot alter inherited column"

Este error indica que una tabla usa herencia de tablas de PostgreSQL. El módulo omite automáticamente estas columnas. La tabla padre debería convertirse, y las hijas heredarán el tipo `BIGINT`.

### Error: "cannot alter type of a column used by a view or rule"

Este error no debería ocurrir, ya que el módulo detecta y maneja vistas automáticamente. Si ocurre:

1. Verifique los logs para ver si hubo un error al recrear la vista
2. Recrear la vista manualmente si es necesario
3. Reportar el caso para mejorar el manejo de vistas

### Verificar que la migración fue exitosa

Puede verificar que las columnas fueron convertidas ejecutando:

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
AND data_type = 'integer'
ORDER BY table_name, column_name;
```

Si la migración fue exitosa, esta consulta no debería devolver resultados (o solo columnas que no deberían ser BIGINT, como columnas heredadas que se convertirán en la tabla padre).

### Verificar secuencias

```sql
SELECT sequence_name, data_type
FROM information_schema.sequences
WHERE sequence_schema = 'public'
AND data_type != 'bigint';
```

Todas las secuencias deberían ser `bigint` después de la migración.

## Autor

NUMA Extreme Systems

## Licencia

AGPL-3
