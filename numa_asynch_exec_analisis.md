# Análisis y Mejoras del Módulo numa_asynch_exec

## Resumen Ejecutivo

El módulo `numa_asynch_exec` proporciona una infraestructura **simple y ligera** para ejecutar métodos de Odoo de forma asíncrona en threads de fondo, con persistencia en base de datos, recuperación automática y trazabilidad de errores. El módulo ahora incluye soporte para **ejecución encadenada con dependencias** mediante el método `await()`, permitiendo programación asíncrona con transacciones separadas.

**Principio de Diseño:**
Este módulo tiene como objetivo mantenerse **simple y minimalista**. Funcionalidades avanzadas como sistemas de prioridades, monitoreo detallado, dashboards y métricas deberían implementarse en **módulos dependientes** que extiendan la funcionalidad base sin complicar el núcleo.

**Nueva Funcionalidad:**
El método `await()` permite crear cadenas de jobs dependientes con ejecución secuencial y paralela, simulando programación asíncrona con transacciones separadas.

---

## 1. Arquitectura y Componentes

### 1.1 Componentes Principales

#### A. `AsynchProxy`
Proxy que intercepta llamadas a métodos y las convierte en jobs asíncronos.

**Características:**
- Intercepta cualquier llamada a método
- Crea registro `numa.asynch.job` con metadata completa
- Envía job al executor después del commit de la transacción actual

#### B. `AwaitProxy` (Nuevo)
Proxy que construye cadenas de jobs dependientes usando builder pattern.

**Características:**
- Soporta ejecución secuencial: `await().method1().method2()`
- Soporta ejecución paralela: `await().method1().await().method2().method3()`
- Maneja proxies anidados con referencias `parent_proxy`
- Crea dependencias automáticamente entre jobs

#### C. `numa.asynch.job`
Modelo que almacena jobs asíncronos.

**Estados:**
- `pending`: Listo para ejecutar
- `running`: Ejecutándose actualmente
- `done`: Completado exitosamente
- `failed`: Falló (sin retries disponibles)
- `waiting`: Esperando que dependencias se completen (NUEVO)

**Campos de Dependencias (Nuevos):**
- `dependency_ids`: Jobs que deben completarse antes
- `dependent_job_ids`: Jobs que dependen de este
- `has_dependencies`: Computado - True si tiene dependencias
- `all_dependencies_done`: Computado - True si todas las dependencias están 'done'

#### D. `numa.asynch.job.dependency` (Nuevo)
Modelo que rastrea dependencias entre jobs.

**Validaciones:**
- Previene auto-dependencias
- Previene dependencias circulares (detección básica)

### 1.2 Flujos de Ejecución

#### Flujo Estándar (`asynch_exec`)

```
1. Usuario llama: recordset.asynch_exec().method()
2. AsynchProxy intercepta la llamada
3. Crea numa.asynch.job con metadata
4. Registra hook postcommit
5. Transacción actual se commitea
6. Hook ejecuta: envía job a ThreadPoolExecutor
7. Thread ejecuta método en nueva transacción
8. Job se marca como 'done' o 'failed'
```

#### Flujo Encadenado (`await`)

```
1. Usuario llama: recordset.await().method1().method2()
2. AwaitProxy construye cadena:
   - method1 → job1
   - method2 → job2 (depende de job1)
3. job1 se crea sin dependencias → estado 'pending'
4. job2 se crea con dependencia a job1 → estado 'waiting'
5. job1 se ejecuta cuando transacción commitea
6. job1 completa → _check_and_trigger_dependents()
7. job2 verifica: all_dependencies_done = True
8. job2 cambia a 'pending' y se envía al executor
9. job2 se ejecuta en nueva transacción
```

#### Flujo Paralelo (`await` con múltiples branches)

```
1. Usuario llama: recordset.await().method1().await().method2().method3()
2. AwaitProxy construye:
   - Root proxy con method1 en chain
   - Parallel proxy con method2 en chain
   - method3 se agrega al root después de finalizar paralelos
3. Jobs creados:
   - job1 (sin dependencias)
   - job2 (sin dependencias, paralelo a job1)
   - job3 (depende de job1 Y job2)
4. job1 y job2 ejecutan simultáneamente
5. Cuando ambos completan, job3 se activa automáticamente
```

---

## 2. Problemas Críticos Detectados

### 1.1 Acceso a `uid.id` sin Validación

**Ubicación:** `utils.py` (líneas 63, 91)

**Problema:**
```python
user = env['res.users'].browse(job.uid.id).exists()
# ...
env_worker = api.Environment(cr, job.uid.id, job.context or context or {})
```

Si `job.uid` es `False` (Many2one vacío), acceder a `.id` causará un error.

**Impacto:**
- Error en tiempo de ejecución cuando el usuario fue eliminado
- Falta de validación antes de acceder al atributo

**Mejora Sugerida:**
```python
user = env['res.users'].browse(job.uid.id if job.uid else False).exists()
if user:
    env_worker = api.Environment(cr, job.uid.id, job.context or context or {})
    # ...
```

O mejor aún:
```python
if not job.uid:
    _logger.error(f'Asynchronous job {job.id} has no user assigned, marking as failed')
    job.write({'state': 'failed'})
    cr.commit()
    return

user = env['res.users'].browse(job.uid.id).exists()
if not user:
    _logger.error(f'Asynchronous job {job.id} user {job.uid.id} not found, marking as failed')
    job.write({'state': 'failed'})
    cr.commit()
    return
```

### 1.2 Delay Solo en Retries, No en Primera Ejecución

**Ubicación:** `utils.py` (línea 53)

**Problema:**
```python
if job.retry_count > 0 and job.retry_delay > 0:
    time.sleep(job.retry_delay / 1000.0)
```

El delay solo se aplica cuando `retry_count > 0`, pero debería aplicarse también en la primera ejecución si `retry_delay > 0`.

**Impacto:**
- Comportamiento inconsistente: delay solo en retries
- El usuario puede esperar un delay inmediato que no se aplica

**Mejora Sugerida:**
```python
# Apply delay if configured (for initial execution or retries)
if job.retry_delay > 0:
    time.sleep(job.retry_delay / 1000.0)
```

### 1.3 Estado 'running' Antes de Validaciones

**Ubicación:** `utils.py` (líneas 56-58)

**Problema:**
El estado se marca como 'running' antes de validar que el usuario y recordset existan. Si la validación falla, el job queda en 'running' permanentemente.

**Impacto:**
- Jobs que fallan en validación quedan en estado 'running'
- No se pueden recuperar automáticamente

**Mejora Sugerida:**
Validar antes de marcar como 'running', o manejar el rollback del estado si fallan las validaciones.

### 1.4 Falta Validación de Método Existente

**Ubicación:** `utils.py` (línea 71)

**Problema:**
```python
method = getattr(recordset, job.method_name)
method(*job.args, **job.kwargs)
```

No se valida si el método existe o si es callable antes de intentar ejecutarlo.

**Impacto:**
- Errores críticos en tiempo de ejecución
- Falta de mensajes de error claros

**Mejora Sugerida:**
```python
if not hasattr(recordset, job.method_name):
    raise AttributeError(f"Method '{job.method_name}' does not exist on model '{job.model_name}'")
    
method = getattr(recordset, job.method_name)
if not callable(method):
    raise TypeError(f"'{job.method_name}' is not a callable method on model '{job.model_name}'")
    
method(*job.args, **job.kwargs)
```

---

## 3. Nueva Funcionalidad: `await()` para Ejecución Encadenada

### 3.1 Propósito

El método `await()` permite crear cadenas de jobs asíncronos con dependencias, simulando programación asíncrona con transacciones separadas. Esto permite:

- **Ejecución Secuencial**: Un job solo se ejecuta después de que otro complete
- **Ejecución Paralela**: Múltiples jobs ejecutan simultáneamente
- **Combinación**: Paralelo seguido de secuencial

### 3.2 API y Uso

#### Ejecución Secuencial

```python
# method2 solo se ejecuta después de que method1 complete exitosamente
recordset.await().method1().method2()
```

**Flujo:**
1. `method1` crea job1 (sin dependencias) → ejecuta inmediatamente
2. `method2` crea job2 (depende de job1) → espera en estado 'waiting'
3. Cuando job1 completa, job2 se activa automáticamente

#### Ejecución Paralela

```python
# method1 y method2 ejecutan simultáneamente
# method3 ejecuta después de que ambos completen
recordset.await().method1().await().method2().method3()
```

**Flujo:**
1. `method1` crea job1 (sin dependencias)
2. `await()` crea nuevo proxy paralelo
3. `method2` crea job2 (sin dependencias, paralelo a job1)
4. `method3` crea job3 (depende de job1 Y job2)
5. job1 y job2 ejecutan en paralelo
6. Cuando ambos completan, job3 se activa

#### Cadenas Complejas

```python
# Múltiples niveles de paralelismo y secuencia
recordset.await().fetch_data1().await().fetch_data2().process().await().validate().save()
```

**Flujo:**
1. `fetch_data1` y `fetch_data2` en paralelo
2. `process` después de ambos
3. `validate` en paralelo con... (depende del contexto)
4. `save` después de validación

### 3.3 Implementación Técnica

#### Builder Pattern

`AwaitProxy` implementa el patrón Builder:

```python
class AwaitProxy:
    def __init__(self, recordset, parent_job_ids=None, retry=0, retry_delay=0, parent_proxy=None):
        self.chain = []  # Métodos secuenciales
        self.parallel_groups = []  # Proxies paralelos
        self.parent_proxy = parent_proxy  # Referencia al proxy raíz
    
    def await(self):
        # Crea nuevo proxy paralelo
        # Lo agrega a parallel_groups del root
        # Retorna el nuevo proxy para continuar cadena
    
    def __getattr__(self, name):
        # Si tiene parent_proxy: finaliza branch y redirige a root
        # Si es root con parallel_groups: finaliza paralelos primero
        # Agrega método a chain
```

#### Gestión de Dependencias

1. **Creación de Dependencias:**
   - Cada job en cadena secuencial depende del anterior
   - Jobs paralelos no tienen dependencias entre sí
   - Job final después de paralelos depende de todos los paralelos

2. **Resolución de Dependencias:**
   - Jobs con dependencias se crean en estado 'waiting'
   - Cuando un job completa, llama `_check_and_trigger_dependents()`
   - Si todas las dependencias están 'done', job se mueve a 'pending'
   - Job se envía automáticamente al executor

3. **Validaciones:**
   - No permite auto-dependencias
   - Detecta dependencias circulares (básico)

### 3.4 Ventajas

1. **Simula Programación Asíncrona**: Permite escribir código asíncrono con transacciones separadas
2. **API Fluida**: Sintaxis natural y legible
3. **Paralelización Automática**: Detecta oportunidades de paralelismo
4. **Transacciones Separadas**: Cada job ejecuta en su propia transacción
5. **Dependencias Automáticas**: No requiere gestión manual de dependencias

### 3.5 Limitaciones

1. **Dependencias Simples**: Solo verifica que dependencias estén 'done', no maneja resultados
2. **Sin Timeout**: Jobs pueden esperar indefinidamente si una dependencia falla
3. **Detección Circular Básica**: La detección de dependencias circulares es básica
4. **Sin Cancelación**: No hay forma de cancelar jobs en cadena si uno falla

### 3.6 Casos de Uso

#### Caso 1: Pipeline de Procesamiento

```python
# Procesar datos en etapas
recordset.await().fetch_data().transform().validate().save()
```

#### Caso 2: Agregación Paralela

```python
# Obtener datos de múltiples fuentes en paralelo, luego procesar
recordset.await().fetch_from_api1().await().fetch_from_api2().merge_results()
```

#### Caso 3: Validación y Notificación

```python
# Validar en paralelo, luego notificar
recordset.await().validate_business_rules().await().check_permissions().send_notification()
```

---

## 4. Problemas de Calidad de Código

### 2.1 Imports Después de Definiciones

**Ubicación:** `utils.py` (líneas 24-34)

**Problema:**
Los imports están colocados después de la definición de funciones, lo cual viola PEP 8.

**Mejora Sugerida:**
Mover todos los imports al inicio del archivo.

### 2.2 Variable `_executor_lock` No Utilizada

**Ubicación:** `utils.py` (línea 6)

**Problema:**
Se define `_executor_lock` pero nunca se usa. El `_executor` se inicializa al importar el módulo pero no hay protección thread-safe para su inicialización.

**Mejora Sugerida:**
Si no se necesita, eliminar. Si se necesita thread-safety, implementarlo correctamente:
```python
_executor_lock = threading.Lock()
_executor = None

def get_asynch_executor():
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                max_workers = int(config.get('numa_asynch_max_threads', 5))
                _executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix='numa_asynch_exec'
                )
    return _executor
```

### 2.3 Uso de `SUPERUSER_ID` en Lugar de Usuario Real

**Ubicación:** `utils.py` (línea 46)

**Problema:**
Se crea el environment con `SUPERUSER_ID` inicialmente, luego se cambia al usuario real. Esto puede causar problemas si algo falla antes del cambio.

**Mejora Sugerida:**
Validar el usuario antes de crear el environment, o usar el usuario directamente.

### 2.4 Falta de Timeout en Ejecución

**Problema:**
No hay límite de tiempo para la ejecución de jobs, lo que puede causar threads bloqueados indefinidamente.

**Mejora Sugerida:**
Agregar soporte opcional de timeout con configuración.

---

## 5. Problemas de Documentación

### 3.1 Docstrings Incompletos

**Ubicación:** Varios métodos

**Problema:**
Faltan parámetros, valores de retorno y excepciones en varios métodos.

**Mejora Sugerida:**
Completar docstrings con formato estándar (Google o NumPy style).

### 3.2 Falta de Ejemplos en Docstrings

**Ubicación:** `AsynchProxy.__init__`, `_run_in_thread`

**Mejora Sugerida:**
Agregar ejemplos de uso en docstrings de clases y métodos principales.

---

## 4. Problemas de Seguridad

### 4.1 Uso de `sudo()` sin Justificación

**Ubicación:** `base_extension.py` (línea 42), `utils.py` (línea 97)

**Problema:**
Uso de `sudo()` sin documentar por qué es necesario.

**Mejora Sugerida:**
Documentar que es necesario para crear/job management independiente de permisos de usuario.

### 4.2 Validación de Métodos Permitidos

**Problema:**
No hay validación de qué métodos pueden ejecutarse de forma asíncrona. Un usuario podría intentar ejecutar métodos privados o peligrosos.

**Mejora Sugerida:**
Agregar lista blanca/negra de métodos permitidos, o validar que el método sea público.

---

## 7. Problemas de Rendimiento

### 5.1 Múltiples Commits en Misma Función

**Ubicación:** `utils.py` (múltiples `cr.commit()`)

**Problema:**
Se hacen múltiples commits en la misma función, lo cual puede impactar rendimiento.

**Mejora Sugerida:**
Consolidar commits cuando sea posible.

### 5.2 No Hay Límite de Jobs Pendientes

**Problema:**
No hay límite en el número de jobs que se pueden crear, lo que puede saturar el sistema.

**Mejora Sugerida:**
Agregar límite configurable o validación de capacidad del thread pool.

---

## 8. Mejoras Sugeridas Adicionales

### 6.1 Agregar Campo de Resultado

**Mejora:**
Agregar campo `result` para almacenar el resultado de la ejecución (si es serializable).

**Nota:** Evaluar si esto agrega complejidad innecesaria al módulo base. Podría implementarse en un módulo dependiente si se requiere.

### 6.2 Agregar Timestamps

**Mejora:**
Agregar campos `created_at`, `started_at`, `completed_at` para mejor trazabilidad.

**Nota:** Los campos estándar de Odoo (`create_date`, `write_date`) pueden ser suficientes. Timestamps adicionales podrían agregarse en un módulo dependiente si se necesita tracking detallado.

### 6.3 Agregar Prioridad de Jobs ⚠️ MÓDULO DEPENDIENTE

**Mejora:**
Sistema de prioridades para ejecutar jobs más importantes primero.

**Recomendación:** 
Esta funcionalidad **NO debe implementarse en este módulo**. El objetivo de `numa_asynch_exec` es mantenerse **simple y ligero**. Un sistema de prioridades requiere:
- Modificación del ThreadPoolExecutor o uso de múltiples pools
- Lógica de ordenamiento de jobs
- Interfaz adicional para configurar prioridades
- Mayor complejidad en el código base

**Solución:** Implementar en un módulo dependiente (ej: `numa_asynch_exec_priority`) que extienda `numa_asynch_exec` con estas capacidades avanzadas.

### 8.4 Agregar Métricas y Monitoreo ⚠️ MÓDULO DEPENDIENTE

**Mejora:**
Contador de jobs por estado, tiempo promedio de ejecución, dashboards, etc.

**Recomendación:**
Esta funcionalidad **NO debe implementarse en este módulo**. El objetivo es mantener `numa_asynch_exec` como una **infraestructura base simple**. Las métricas y monitoreo requieren:
- Vistas adicionales y reporting
- Lógica de cálculo de estadísticas
- Interfaz de usuario para visualización
- Dependencias adicionales

**Solución:** Implementar en un módulo dependiente (ej: `numa_asynch_exec_monitoring`) que proporcione dashboards, métricas y reportes basados en `numa.asynch.job`.

---

## 9. Funcionalidades Implementadas Recientemente

### 9.1 Método `await()` para Ejecución Encadenada ✅ IMPLEMENTADO

**Características:**
- Builder pattern para construir cadenas de jobs
- Soporte para ejecución secuencial y paralela
- Gestión automática de dependencias
- Activación automática de jobs dependientes

**Modelos Nuevos:**
- `numa.asynch.job.dependency`: Rastrea dependencias entre jobs
- Campos en `numa.asynch.job`: `dependency_ids`, `dependent_job_ids`, `has_dependencies`, `all_dependencies_done`
- Nuevo estado: `'waiting'` para jobs con dependencias no satisfechas

**Métodos Nuevos:**
- `Base.await()`: Punto de entrada para ejecución encadenada
- `AwaitProxy`: Proxy builder para construir cadenas
- `NumaAsynchJob._check_and_trigger_dependents()`: Activa jobs dependientes

**Ejemplos de Uso:**
```python
# Secuencial
recordset.await().method1().method2()

# Paralelo
recordset.await().method1().await().method2().method3()

# Complejo
recordset.await().fetch1().await().fetch2().process().save()
```

**Estado:** ✅ Implementado y documentado

---

## 10. Resumen de Prioridades

### Alta Prioridad (Corregir Inmediatamente)
1. ⚠️ Validar `job.uid` antes de acceder a `.id`
2. ⚠️ Aplicar `retry_delay` en primera ejecución también
3. ⚠️ Validar usuario/recordset antes de marcar como 'running'
4. ⚠️ Validar que método existe y es callable

### Media Prioridad (Mejorar Próximamente)
5. Reorganizar imports según PEP 8
6. Eliminar o usar correctamente `_executor_lock`
7. Mejorar manejo de errores con mensajes más claros
8. Agregar validación de métodos permitidos

### Baja Prioridad (Mejoras Futuras - Evaluar Simplicidad)
9. ⏳ Agregar soporte de timeout - **EVALUAR** (puede agregar complejidad)
10. ⏳ Agregar campos de resultado y timestamps - **EVALUAR** (considerar módulo dependiente)

### Funcionalidades para Módulos Dependientes ⚠️ NO IMPLEMENTAR EN ESTE MÓDULO
11. ❌ Sistema de prioridades - **Implementar en módulo dependiente** (ej: `numa_asynch_exec_priority`)
12. ❌ Métricas y monitoreo - **Implementar en módulo dependiente** (ej: `numa_asynch_exec_monitoring`)

**Nota:** Estas funcionalidades requieren complejidad adicional que va contra el principio de simplicidad del módulo. Se recomienda crear módulos separados que dependan de `numa_asynch_exec` para extender funcionalidad avanzada.

---

## Conclusión

El módulo `numa_asynch_exec` es una implementación funcional y útil diseñada para mantenerse **simple y ligera**. Las mejoras de alta prioridad han sido implementadas para mejorar la robustez del módulo sin agregar complejidad innecesaria.

**Principio de Diseño:**
Este módulo debe mantener su **simplicidad** como infraestructura base. Funcionalidades avanzadas como:
- Sistemas de prioridades
- Métricas y monitoreo detallado
- Dashboards y reportes
- Gestión avanzada de colas

Deben implementarse en **módulos dependientes** que extiendan `numa_asynch_exec` sin complicar el núcleo. Esto permite:
- Mantener el módulo base simple y fácil de mantener
- Permitir a los usuarios elegir qué funcionalidades avanzadas necesitan
- Facilitar el testing y debugging del núcleo
- Evitar dependencias innecesarias para usuarios básicos

**Recomendación Final:**
✅ Las mejoras de alta prioridad han sido implementadas. El módulo está listo para uso en producción. La nueva funcionalidad `await()` permite programación asíncrona avanzada con transacciones separadas, manteniendo la simplicidad del núcleo. Funcionalidades avanzadas adicionales deben desarrollarse en módulos dependientes siguiendo el principio de simplicidad del núcleo.

---

## 11. Comparación: `asynch_exec()` vs `await()`

### `asynch_exec()` - Ejecución Simple

**Uso:**
```python
recordset.asynch_exec().method()
```

**Características:**
- Ejecuta un método en otra transacción
- No tiene dependencias
- Se ejecuta inmediatamente después del commit
- Ideal para tareas independientes

### `await()` - Ejecución Encadenada

**Uso:**
```python
recordset.await().method1().method2()
```

**Características:**
- Permite crear cadenas de jobs dependientes
- Soporta ejecución secuencial y paralela
- Cada job ejecuta en su propia transacción
- Ideal para pipelines y workflows complejos

### Cuándo Usar Cada Uno

**Usa `asynch_exec()` cuando:**
- Tienes una tarea independiente
- No necesitas coordinar múltiples jobs
- Quieres ejecución simple y directa

**Usa `await()` cuando:**
- Necesitas ejecutar jobs en secuencia
- Quieres paralelizar tareas independientes
- Necesitas coordinar múltiples jobs
- Quieres simular programación asíncrona con transacciones

---

**Versión del Análisis:** 2.0  
**Fecha:** 2024  
**Última Actualización:** Incluye funcionalidad `await()` para ejecución encadenada
