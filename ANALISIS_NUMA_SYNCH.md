# Análisis del Sistema de Sincronización Numa Synch

## Resumen Ejecutivo

El sistema **Numa Synch** es una solución de sincronización offline-first para Odoo 18.0 que permite mantener múltiples instancias de Odoo sincronizadas en una arquitectura Master-Slave. El sistema está compuesto por cuatro módulos modulares que trabajan en conjunto:

1. **`numa_synch`** - Módulo core (biblioteca base)
2. **`numa_synch_master`** - Servidor central (Master)
3. **`numa_synch_slave`** - Nodos branch (Slave)
4. **`numa_synch_ai_assisted`** - Adaptación asistida por IA (opcional)

**Versión:** 18.0.1.0.0  
**Autor:** Gustavo Marino <gamarino@numaes.com>  
**Licencia:** LGPL-3  
**Categoría:** Extra Tools

---

## 1. Arquitectura del Sistema

### 1.1 Arquitectura General

```
┌─────────────────────────────────────────────────────────────┐
│                    MASTER (Central Server)                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  numa_synch_master                                       │ │
│  │  - JSON-RPC Endpoint (/numa_synch/api/v1/sync_batch)   │ │
│  │  - Two-Phase Write Strategy                             │ │
│  │  - LWW Conflict Resolution                              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          ▲                                    │
│                          │ HTTP POST (Bearer Token)           │
│                          │                                    │
┌──────────────────────────┴────────────────────────────────────┐
│                    SLAVE 1 (Branch Node)                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  numa_synch_slave                                        │ │
│  │  - Delta Detection (Cron 15 min)                        │ │
│  │  - BFS Dependency Resolution                            │ │
│  │  - Batch Serialization & Transport                      │ │
│  └─────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                    SLAVE 2 (Branch Node)                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  numa_synch_slave                                        │ │
│  │  - Delta Detection (Cron 15 min)                        │ │
│  │  - BFS Dependency Resolution                            │ │
│  │  - Batch Serialization & Transport                      │ │
│  └─────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### 1.2 Módulos y Responsabilidades

#### A. `numa_synch` (Core Module)
**Propósito:** Biblioteca base sin dependencias de red o cron.

**Componentes:**
- **`numa.synch.map`**: Tabla de mapeo de identidades (Local ID ↔ Remote ID)
- **`numa.synch.rule`**: Reglas de sincronización con filtros de dominio
- **`numa.synch.engine`**: Motor abstracto de serialización

**Características:**
- Sin controladores HTTP
- Sin cron jobs
- Modelo abstracto para herencia
- Métodos de serialización reutilizables
- Validación de metadatos y esquema estricto
- Generación de hashes de esquema para compatibilidad

#### B. `numa_synch_master` (Master Server)
**Propósito:** Servidor central que recibe y procesa datos de Slaves.

**Componentes:**
- **Controller**: Endpoint JSON-RPC `/numa_synch/api/v1/sync_batch`
- **Engine Master**: Implementación de Two-Phase Write

**Características:**
- Two-Phase Write Strategy (Skeleton + Decoration)
- Last Write Wins (LWW) conflict resolution
- Namespace Safety (solo modelos permitidos)
- Reference Safety (manejo graceful de referencias faltantes)
- Validación estricta de metadatos (versión, esquema)
- Prevención de corrupción de datos por incompatibilidades

#### C. `numa_synch_slave` (Branch Node)
**Propósito:** Nodo branch que detecta cambios locales y los envía al Master.

**Componentes:**
- **Connection Model**: Configuración de conexión al Master
- **Engine Slave**: Lógica de detección y envío
- **Cron Job**: Sincronización programada (configurable por conexión)

**Características:**
- Delta detection basado en `write_date`
- BFS exploration para dependencias Many2one
- Batch processing con commits atómicos
- UUID automático para identificación única
- Frecuencia de sincronización configurable por conexión
- Hora programada opcional para sincronizaciones diarias

#### D. `numa_synch_ai_assisted` (AI-Powered Adapter) - Opcional
**Propósito:** Adaptador inteligente que usa IA para resolver incompatibilidades de esquema.

**Componentes:**
- **AI Map Model**: Almacena mapeos generados por IA
- **Issue Model**: Registra análisis de brechas cuando IA no puede resolver
- **Engine Extension**: Extiende el engine con lógica asistida por IA

**Características:**
- Adaptación automática de esquemas usando IA
- Cache de mapeos para evitar llamadas repetidas
- Análisis de brechas detallado cuando IA falla
- Transformación transparente de payloads
- Scripts de transformación para conversiones complejas
- Integración con `numa_ai` para análisis de esquemas

---

## 2. Flujos de Sincronización

### 2.1 Flujo Slave → Master (Outgoing)

```
┌──────────────────────────────────────────────────────────────┐
│  SLAVE: Cron Trigger (cada 15 minutos)                      │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  1. Discovery (Delta Detection)                              │
│     - Obtener reglas activas (bidirectional/outgoing)        │
│     - Para cada regla: get_delta_domain(last_sync_date)      │
│     - Buscar registros modificados desde last_sync_date      │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  2. Dependency Resolution (BFS)                             │
│     - Para cada registro encontrado:                        │
│       - Encontrar dependencias Many2one                      │
│       - Si dependencia no está mapeada → agregar a cola      │
│       - Continuar BFS hasta agotar dependencias            │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  3. Serialization                                            │
│     - Para cada registro: _serialize_record()               │
│     - Convertir Many2one a {'__type__': 'ref', ...}         │
│     - Convertir Date/Datetime a strings                      │
│     - Manejar Binary fields (si está configurado)            │
│     - Manejar Computed fields (según configuración)         │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  3.5. Metadata Preparation                                   │
│     - Extraer modelos únicos de registros serializados      │
│     - Generar metadata del sistema (odoo_version, db_uuid)   │
│     - Calcular hashes SHA256 de esquema por modelo           │
│     - Incluir configuración de sync_rule en hash              │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  4. Batching                                                 │
│     - Dividir en lotes de tamaño batch_size (default: 100)   │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  5. Transport (HTTP POST)                                    │
│     POST /numa_synch/api/v1/sync_batch                       │
│     Headers: Authorization: Bearer {api_key}                │
│     Body: {                                                  │
│       "slave_token": "uuid",                                 │
│       "meta": {                                              │
│         "system": {"odoo_version": "...", "db_uuid": "..."},│
│         "models": {"res.partner": "hash...", ...}         │
│       },                                                      │
│       "records": [...]                                      │
│     }                                                        │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  MASTER: Process Batch                                       │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  6. Response Processing                                      │
│     - Si éxito: actualizar mappings con Master IDs           │
│     - Commit transaction (por batch)                         │
│     - Si falla: rollback, no actualizar last_sync_date      │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  7. Finalization                                             │
│     - Si todos los batches exitosos:                         │
│       - Actualizar connection.last_sync_date                 │
│     - Si algún batch falla:                                  │
│       - No actualizar last_sync_date (Time Safety)           │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 Flujo Master: Two-Phase Write

```
┌──────────────────────────────────────────────────────────────┐
│  MASTER: Receive Batch                                       │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  VALIDATION: Metadata & Schema Check                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 1. Validar versión de Odoo (debe coincidir exactamente)│ │
│  │ 2. Validar hashes de esquema de modelos                │ │
│  │ 3. Si hay incompatibilidad:                             │ │
│  │    - Lanzar UserError y detener procesamiento          │ │
│  │    - Prevenir corrupción de datos                       │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  PHASE 1: Skeleton Creation                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Para cada registro:                                    │ │
│  │ 1. Verificar si existe mapping (slave_id → master_id) │ │
│  │ 2. Si NO existe:                                        │ │
│  │    - Crear registro con SOLO campos escalares          │ │
│  │    - Ignorar Many2one, One2many, Many2many             │ │
│  │    - Crear mapping (master_id ↔ slave_id)              │ │
│  │ 3. Si EXISTE:                                            │ │
│  │    - Aplicar LWW conflict resolution                    │ │
│  │    - Comparar write_date (Slave vs Master)             │ │
│  │    - Si Slave más nuevo: actualizar campos escalares   │ │
│  │    - Si Master más nuevo: ignorar, log en chatter      │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  PHASE 2: Decoration (Relations)                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Para cada registro:                                    │ │
│  │ 1. Extraer campos relacionales (Many2one, x2many)     │ │
│  │ 2. Traducir referencias:                                │ │
│  │    - _parse_incoming_ref() para Many2one               │ │
│  │    - Buscar master_id usando slave_id en mapping       │ │
│  │ 3. Si referencia no encontrada:                         │ │
│  │    - Log warning, skip field (Reference Safety)        │ │
│  │ 4. Escribir campos relacionales con write()            │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  Return Response                                             │
│  {                                                           │
│    "status": "success",                                      │
│    "updated_mappings": [                                     │
│      {"model": "...", "slave_id": 123, "master_id": 456}    │
│    ]                                                         │
│  }                                                           │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Componentes Clave

### 3.1 Identity Mapping (`numa.synch.map`)

**Propósito:** Traducir IDs locales a IDs remotos.

**Estructura:**
- `model_id`: Referencia a `ir.model`
- `model_name`: Nombre técnico del modelo (indexado)
- `local_id`: ID en la base de datos local (indexado)
- `remote_id`: ID en la base de datos remota (indexado)
- `node_token`: Identificador del nodo remoto (indexado)
- `last_sync_date`: Timestamp de última sincronización

**Constraints:**
- Único: `(model_id, local_id, node_token)`

**Métodos:**
- `get_remote_id(model_name, local_id, node_token)`: Obtener ID remoto
- `get_local_id(model_name, remote_id, node_token)`: Obtener ID local
- `set_mapping(...)`: Crear/actualizar mapping (idempotente)

**Perspectiva:**
- **Desde Slave**: `local_id` = slave_id, `remote_id` = master_id, `node_token` = 'MASTER'
- **Desde Master**: `local_id` = master_id, `remote_id` = slave_id, `node_token` = slave_uuid

### 3.2 Synchronization Rules (`numa.synch.rule`)

**Propósito:** Definir qué registros sincronizar y en qué dirección.

**Campos:**
- `name`: Nombre descriptivo
- `model_id`: Modelo a sincronizar
- `domain_filter`: Filtro de dominio (widget domain)
- `direction`: bidirectional, outgoing, incoming
- `active`: Activar/desactivar regla

**Métodos:**
- `get_delta_domain(last_sync_date)`: Combina dominio usuario + `write_date > last_sync_date`

**Uso:**
- **Slave**: Busca reglas con `direction IN ('bidirectional', 'outgoing')`
- **Master**: Busca reglas con `direction IN ('bidirectional', 'incoming')` para Namespace Safety

### 3.3 Serialization Engine (`numa.synch.engine`)

**Métodos Abstractos:**
- `_serialize_record(record, sync_rule=None)`: Serializa un registro a dict
  - Many2one → `{'__type__': 'ref', 'model': '...', 'id': ...}`
  - Date/Datetime → strings ISO
  - Binary → Serialización opcional con compresión (según sync_rule)
  - Computed fields → Según configuración (stored vs non-stored)
  - Retorna: `(vals_dict, dependencies_list)`

- `_parse_incoming_ref(ref_dict, source_node)`: Parsea referencia entrante
  - Busca mapping usando `numa.synch.map`
  - Retorna: `local_id` o `False`

**Métodos de Validación (Nuevos):**
- `_get_system_metadata()`: Genera metadata del sistema
  - `odoo_version`: Versión de Odoo (ej: "18.0")
  - `db_uuid`: UUID de la base de datos
  - `module_version`: Versión instalada de numa_synch

- `_compute_model_hash(model_name, sync_rule=None)`: Calcula hash SHA256 del esquema
  - Incluye: nombre, tipo, required, relación (para campos relacionales)
  - Respeta configuración de sync_rule (computed fields, binary)
  - Determinístico (orden alfabético de campos)
  - Retorna: Hash SHA256 hexadecimal

- `_validate_metadata(incoming_meta, active_models)`: Valida metadata entrante
  - Verifica versión de Odoo (debe coincidir exactamente)
  - Verifica hashes de esquema de modelos
  - Lanza `UserError` si hay incompatibilidad
  - Previene corrupción de datos por esquemas incompatibles

### 3.4 Two-Phase Write Strategy

**Problema Resuelto:** Dependencias circulares (ej: SaleOrder ↔ StockPicking)

**Fase 1: Skeleton**
- Crea registros con solo campos escalares
- Ignora relaciones (Many2one, x2many)
- Crea mappings inmediatamente

**Fase 2: Decoration**
- Procesa campos relacionales
- Traduce referencias usando mappings creados en Fase 1
- Maneja referencias faltantes gracefully

**Ventajas:**
- Resuelve dependencias circulares
- Permite procesamiento en batch
- Mappings disponibles inmediatamente

### 3.5 Last Write Wins (LWW) Conflict Resolution

**Estrategia:** Comparar `write_date` entre Slave y Master.

**Lógica:**
```
if incoming_write_date > master_write_date:
    # Slave es más nuevo → aplicar cambios
    update_scalar_fields()
    log_chatter("Updated from Slave")
else:
    # Master es más nuevo → ignorar cambios
    log_chatter("Ignored update from Slave (Master is newer)")
```

**Ventajas:**
- Simple y determinístico
- No requiere merge complejo
- Logging en chatter para auditoría

**Limitaciones:**
- Puede perder cambios si hay ediciones simultáneas
- No resuelve conflictos de campo específico

### 3.6 Delta Detection

**Mecanismo:** Basado en `write_date` y reglas de sincronización.

**Proceso:**
1. Obtener `last_sync_date` de la conexión
2. Para cada regla activa:
   - `rule.get_delta_domain(last_sync_date)`
   - Combina dominio usuario + `[('write_date', '>', last_sync_date)]`
   - Buscar registros modificados

**Ventajas:**
- Eficiente (solo registros modificados)
- Configurable por regla
- Soporta filtros complejos

**Consideraciones:**
- Requiere `write_date` preciso
- No detecta cambios en campos computados no almacenados

### 3.7 BFS Dependency Resolution

**Problema:** Un registro puede depender de otros que no fueron modificados recientemente.

**Solución:** BFS exploration de dependencias Many2one.

**Algoritmo:**
```
queue = deque([modified_records])
discovered = set()

while queue:
    record = queue.popleft()
    if record not in discovered:
        add_to_sync_list(record)
        discovered.add(record)
        
        # Encontrar dependencias Many2one
        for m2o_field in record._fields:
            if m2o_field.type == 'many2one':
                dependency = record[m2o_field]
                if dependency and dependency not in discovered:
                    queue.append(dependency)
```

**Ventajas:**
- Asegura que dependencias estén sincronizadas
- Evita referencias rotas
- Procesa en orden correcto

---

## 4. Fortalezas del Sistema

### 4.1 Arquitectura Modular
- **Separación de responsabilidades**: Core, Master, Slave en módulos separados
- **Reutilización**: Core puede usarse independientemente
- **Extensibilidad**: Fácil agregar nuevas funcionalidades

### 4.2 Offline-First
- **Tolerancia a fallos**: Si un batch falla, no se actualiza `last_sync_date`
- **Reintentos automáticos**: El cron reintenta en el próximo ciclo
- **Estado consistente**: Mappings se actualizan solo si todo el batch tiene éxito

### 4.3 Seguridad
- **Namespace Safety**: Solo modelos permitidos en reglas pueden sincronizarse
- **Reference Safety**: Referencias faltantes no causan crashes
- **Autenticación**: Bearer token para autenticación API
- **UUID único**: Cada Slave tiene un token único e inmutable
- **Validación de Esquema**: Verificación estricta de compatibilidad antes de procesar
- **Prevención de Corrupción**: Detección temprana de incompatibilidades de esquema

### 4.4 Performance
- **Batch Processing**: Procesa múltiples registros en una sola request
- **Delta Detection**: Solo sincroniza registros modificados
- **Índices**: Tabla de mapping con índices en campos clave
- **Commits atómicos**: Un commit por batch, no por registro

### 4.5 Flexibilidad
- **Domain Filters**: Filtros complejos usando dominio de Odoo
- **Dirección configurable**: Bidirectional, outgoing, incoming
- **Batch size configurable**: Ajustable según ancho de banda
- **Cron configurable**: Intervalo modificable

---

## 5. Áreas de Mejora y Consideraciones

### 5.1 Limitaciones Actuales

#### A. Sincronización Unidireccional (Slave → Master)
- **Problema**: Solo sincroniza cambios del Slave al Master
- **Impacto**: Cambios en Master no se propagan automáticamente a Slaves
- **Solución futura**: Implementar sincronización bidireccional completa

#### B. Last Write Wins puede perder datos
- **Problema**: Si dos nodos editan simultáneamente, se pierden cambios
- **Impacto**: Conflictos de edición simultánea
- **Solución futura**: Merge automático o resolución manual de conflictos

#### C. ~~No hay sincronización de campos Binary~~ ✅ IMPLEMENTADO
- ~~**Problema**: Campos binarios se ignoran por performance~~
- ~~**Impacto**: Archivos adjuntos no se sincronizan~~
- ✅ **Solución implementada**: Sincronización opcional de binary con compresión (configurable por regla)

#### D. No hay manejo de eliminaciones
- **Problema**: Registros eliminados no se sincronizan
- **Impacto**: Registros eliminados en Slave permanecen en Master
- **Solución futura**: Implementar soft delete o sincronización de eliminaciones

#### E. Cron fijo de 15 minutos
- **Problema**: No es configurable por conexión
- **Impacto**: Todas las conexiones sincronizan al mismo ritmo
- **Solución futura**: Intervalo configurable por conexión

### 5.2 Mejoras Sugeridas

#### A. Sincronización Bidireccional Completa
```python
# En Master: detectar cambios y notificar a Slaves
# En Slave: recibir notificaciones y aplicar cambios
```

#### B. Conflict Resolution Avanzado
- Merge automático para campos no conflictivos
- Resolución manual para conflictos complejos
- Historial de conflictos

#### C. Compresión de Payloads
- Comprimir JSON antes de enviar
- Reducir ancho de banda en conexiones lentas

#### D. Retry Logic con Exponential Backoff
- Reintentos automáticos con backoff exponencial
- Manejo de rate limiting del Master

#### E. Métricas y Monitoreo
- Dashboard de estado de sincronización
- Métricas de latencia, throughput, errores
- Alertas para fallos repetidos

#### F. ~~Validación de Datos~~ ✅ PARCIALMENTE IMPLEMENTADO
- ✅ Validación de metadatos y esquema (IMPLEMENTADO)
- ⚠️ Validación de valores de campos antes de aplicar (PENDIENTE)
- ⚠️ Rollback automático en caso de errores de validación (PENDIENTE)

#### G. ~~Soporte para Campos Computados~~ ✅ IMPLEMENTADO
- ✅ Sincronizar campos computados almacenados (IMPLEMENTADO)
- ✅ Recalcular campos computados en destino (IMPLEMENTADO)

### 5.3 Nuevas Funcionalidades Implementadas

#### A. Soporte para Campos Binary
- **Implementación**: Serialización base64 con compresión opcional (gzip)
- **Configuración**: Por regla de sincronización
- **Límites**: Tamaño máximo configurable (default: 10 MB)
- **Performance**: Compresión automática si reduce tamaño
- **Estado**: ✅ Implementado

#### B. Soporte para Campos Computados
- **Campos almacenados (store=True)**: Sincronizados directamente
- **Campos no almacenados (store=False)**: Recalculados en destino
- **Configuración**: Por regla de sincronización
- **Performance**: Recalculación automática después de escrituras
- **Estado**: ✅ Implementado

#### C. Validación de Metadatos y Esquema Estricto
- **Implementación**: Validación de compatibilidad antes de procesar batches
- **Componentes**:
  - `_get_system_metadata()`: Genera metadata del sistema (versión, UUID, módulo)
  - `_compute_model_hash()`: Calcula hash SHA256 determinístico del esquema del modelo
  - `_validate_metadata()`: Valida metadata entrante contra sistema local
- **Validaciones**:
  1. **Versión de Odoo**: Debe coincidir exactamente entre Slave y Master
  2. **Hashes de Esquema**: Estructura de modelos debe ser idéntica
  3. **DB UUID**: Log informativo (opcional, no bloquea)
- **Comportamiento**:
  - Si hay incompatibilidad: Lanza `UserError` y detiene procesamiento
  - No hay adaptación dinámica: Falla de forma segura
  - Prevención de corrupción: No procesa datos con esquemas incompatibles
- **Hash de Esquema**: Incluye nombre, tipo, required, relación (para campos relacionales)
- **Respeto a Configuración**: Hash considera sync_rule (computed fields, binary)
- **Estado**: ✅ Implementado

#### D. Configuración de Frecuencia de Sincronización por Conexión
- **Implementación**: Cada conexión Slave puede tener su propia frecuencia
- **Componentes**:
  - `sync_interval_number`: Número de intervalos (default: 15)
  - `sync_interval_type`: Tipo de intervalo (minutes/hours/days)
  - `use_scheduled_time`: Activar hora programada
  - `sync_schedule_time`: Hora específica del día (formato 24h)
  - `cron_id`: Cron job dinámico asociado
- **Características**:
  - Creación automática de cron jobs por conexión
  - Actualización automática cuando cambian los ajustes
  - Eliminación automática al borrar conexión
  - Cálculo automático de `nextcall` para horas programadas
- **Estado**: ✅ Implementado

#### E. Adaptación Asistida por IA (numa_synch_ai_assisted)
- **Implementación**: Módulo opcional que extiende validación con IA
- **Componentes**:
  - `numa.synch.ai.map`: Almacena mapeos generados por IA
  - `numa.synch.issue`: Registra análisis de brechas cuando IA no puede resolver
  - Engine extension: Override de `_validate_metadata()` y `process_incoming_batch_master()`
- **Flujo**:
  1. Validación estándar falla
  2. Busca mapeo en cache
  3. Si no hay cache, invoca IA para análisis
  4. Si confianza alta (>0.9) y sin issues críticos → crea mapeo y continúa
  5. Si confianza baja o issues críticos → registra gap analysis y aborta
- **Características**:
  - Mapeo automático de campos basado en similitud semántica
  - Cache de mapeos para performance
  - Scripts de transformación para conversiones complejas
  - Análisis detallado de brechas con sugerencias
  - Integración con `numa_ai` engine
- **Estado**: ✅ Implementado

### 5.4 Consideraciones de Escalabilidad

#### A. Múltiples Slaves
- **Actual**: Soporta múltiples Slaves
- **Limitación**: Master procesa secuencialmente
- **Mejora**: Procesamiento paralelo de batches de diferentes Slaves

#### B. Volumen de Datos
- **Actual**: Batch size configurable (default: 100)
- **Limitación**: Procesamiento en memoria
- **Mejora**: Streaming para lotes muy grandes

#### C. Base de Datos
- **Actual**: Índices en campos clave
- **Limitación**: Búsquedas lineales en algunos casos
- **Mejora**: Índices compuestos adicionales

### 5.4 Consideraciones de Seguridad

#### A. Autenticación
- **Actual**: Bearer token (API Key)
- **Mejora**: OAuth 2.0, JWT tokens con expiración

#### B. Encriptación
- **Actual**: HTTP (no HTTPS requerido)
- **Mejora**: Forzar HTTPS, validar certificados

#### C. Rate Limiting
- **Actual**: No implementado
- **Mejora**: Rate limiting por Slave token

#### D. Validación de Datos
- **Actual**: Validación básica + validación de metadatos y esquema
- **Mejora**: Validación estricta de valores de campos, constraints

---

## 6. Casos de Uso

### 6.1 Sucursales Offline
**Escenario**: Múltiples sucursales con conectividad intermitente.

**Solución**: Cada sucursal es un Slave, sincroniza con Master central cuando hay conexión.

**Ventajas**:
- Funciona offline
- Sincronización automática cuando hay conexión
- Datos centralizados en Master

### 6.2 Replicación de Datos
**Escenario**: Replicar datos entre instancias de Odoo.

**Solución**: Configurar reglas de sincronización para modelos específicos.

**Ventajas**:
- Control granular de qué sincronizar
- Filtros de dominio flexibles
- Dirección configurable

### 6.3 Migración Gradual
**Escenario**: Migrar datos de un sistema legacy a Odoo.

**Solución**: Usar Slave como puente, sincronizar datos gradualmente.

**Ventajas**:
- Migración incremental
- Validación de datos durante migración
- Rollback fácil

---

## 7. Comparación con Alternativas

### 7.1 vs. Odoo Replication (PostgreSQL)
**Numa Synch:**
- ✅ Control granular por modelo
- ✅ Filtros de dominio
- ✅ Transformación de datos
- ✅ Resolución de conflictos
- ❌ Overhead de serialización

**PostgreSQL Replication:**
- ✅ Replicación completa
- ✅ Bajo overhead
- ❌ No hay filtros granulares
- ❌ No hay transformación

### 7.2 vs. ETL Tools
**Numa Synch:**
- ✅ Integrado en Odoo
- ✅ Usa modelos nativos
- ✅ Automático (cron)
- ❌ Limitado a Odoo

**ETL Tools:**
- ✅ Multiplataforma
- ✅ Transformaciones complejas
- ❌ Requiere configuración externa
- ❌ No integrado

---

## 8. Conclusión

El sistema **Numa Synch** proporciona una solución robusta y flexible para sincronización offline-first en Odoo. Su arquitectura modular, estrategia Two-Phase Write, y manejo de conflictos LWW lo hacen adecuado para escenarios de múltiples sucursales y replicación de datos.

### Fortalezas Principales:
1. ✅ Arquitectura modular y extensible
2. ✅ Offline-first con tolerancia a fallos
3. ✅ Two-Phase Write resuelve dependencias circulares
4. ✅ Seguridad con namespace y reference safety
5. ✅ Performance con batch processing y delta detection
6. ✅ Validación estricta de metadatos y esquema (previene corrupción)
7. ✅ Soporte para campos binary con compresión
8. ✅ Soporte para campos computados (stored y non-stored)
9. ✅ Configuración flexible de frecuencia por conexión
10. ✅ Adaptación asistida por IA para sistemas no-Odoo (opcional)

### Áreas de Mejora:
1. ⚠️ Sincronización bidireccional completa
2. ⚠️ Manejo de eliminaciones
3. ✅ Sincronización de campos binary (IMPLEMENTADO)
4. ⚠️ Conflict resolution más avanzado
5. ⚠️ Métricas y monitoreo
6. ✅ Soporte para campos computados (IMPLEMENTADO)
7. ✅ Validación de metadatos y esquema estricto (IMPLEMENTADO)
8. ✅ Configuración de frecuencia por conexión (IMPLEMENTADO)
9. ✅ Adaptación asistida por IA (IMPLEMENTADO)

### Recomendación:
El sistema está listo para uso en producción para casos de uso de sincronización unidireccional (Slave → Master). Para sincronización bidireccional completa, se recomienda implementar las mejoras sugeridas.

---

---

## 9. Protocolo de Validación de Metadatos

### 9.1 Estructura de Metadata

El sistema implementa validación estricta de metadatos para asegurar compatibilidad entre Slave y Master antes de procesar cualquier dato.

**Estructura del Payload:**
```json
{
  "slave_token": "uuid-string",
  "meta": {
    "system": {
      "odoo_version": "18.0",
      "db_uuid": "database-uuid",
      "module_version": "18.0.1.0.0"
    },
    "models": {
      "res.partner": "sha256_hash_string...",
      "sale.order": "sha256_hash_string...",
      ...
    }
  },
  "records": [...]
}
```

### 9.2 Generación de Metadata (Slave)

**Proceso:**
1. Después de serialización, extraer modelos únicos de registros
2. Generar metadata del sistema usando `_get_system_metadata()`
3. Para cada modelo activo:
   - Obtener sync_rule correspondiente (si existe)
   - Calcular hash usando `_compute_model_hash(model_name, sync_rule)`
4. Incluir metadata solo en el primer batch (evita redundancia)

**Hash de Esquema:**
- Incluye: nombre de campo, tipo, required, relación (para campos relacionales)
- Excluye: campos del sistema (id, create_date, write_date, etc.)
- Respeta: configuración de sync_rule (computed fields, binary)
- Determinístico: orden alfabético de campos

### 9.3 Validación de Metadata (Master)

**Proceso:**
1. Extraer metadata del payload JSON
2. Si metadata presente, validar antes de procesar batch
3. Validaciones:
   - **Versión de Odoo**: Debe coincidir exactamente
   - **Hashes de Esquema**: Deben coincidir para cada modelo
   - **DB UUID**: Log informativo (no bloquea)

**Comportamiento en Error:**
- Si versión no coincide: `UserError("Version Mismatch: ...")`
- Si hash no coincide: `UserError("Schema Mismatch in model ...")`
- Procesamiento se detiene inmediatamente
- No se procesa ningún registro del batch

### 9.4 Ventajas de la Validación

1. **Prevención de Corrupción**: Detecta incompatibilidades antes de escribir datos
2. **Detección Temprana**: Falla rápido, antes de procesar registros
3. **Mensajes Claros**: Errores descriptivos indican qué modelo tiene problema
4. **Determinístico**: Hash siempre igual para mismo esquema
5. **Configurable**: Respeta configuración de sync_rule

### 9.5 Casos de Uso

**Escenario 1: Actualización de Módulo**
- Slave actualiza módulo que agrega campo nuevo
- Master aún no tiene el módulo actualizado
- Hash de esquema difiere → Error detectado antes de procesar
- Solución: Actualizar Master primero

**Escenario 2: Versión de Odoo Diferente**
- Slave en Odoo 18.0, Master en Odoo 17.0
- Versión no coincide → Error detectado inmediatamente
- Solución: Actualizar ambos a misma versión

**Escenario 3: Configuración Diferente**
- Slave tiene sync_rule con `sync_computed_fields=True`
- Master tiene sync_rule con `sync_computed_fields=False`
- Hash considera configuración → Diferencia detectada
- Solución: Sincronizar configuración de reglas

---

---

## 10. Adaptación Asistida por IA

### 10.1 Propósito

El módulo `numa_synch_ai_assisted` extiende el sistema de sincronización con capacidades de adaptación inteligente de esquemas usando Inteligencia Artificial. Actúa como un **adaptador de fallback** cuando la validación estándar de metadatos falla, permitiendo sincronizar con sistemas no-Odoo o sistemas con esquemas modificados.

### 10.2 Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│  MASTER: Receive Batch                                       │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  Standard Metadata Validation                                │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ├─ Success → Process Batch
                        │
                        └─ Failure → AI-Assisted Flow
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Check Cache (AI Map)          │
                    └───────────┬─────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                        │
                    ▼                        ▼
            Found in Cache          Not Found
                    │                        │
                    │                        ▼
                    │            ┌───────────────────────┐
                    │            │  Invoke AI Analysis    │
                    │            └───────────┬───────────┘
                    │                        │
                    │            ┌───────────┴───────────┐
                    │            │                        │
                    │            ▼                        ▼
                    │    High Confidence          Low Confidence
                    │    (>0.9) + No Issues       OR Critical Issues
                    │            │                        │
                    │            │                        ▼
                    │            │            ┌──────────────────────┐
                    │            │            │  Log Gap Analysis    │
                    │            │            │  Abort Transaction   │
                    │            │            └──────────────────────┘
                    │            │
                    │            ▼
                    │    ┌──────────────────────┐
                    │    │  Create AI Mapping   │
                    │    │  Cache for Future    │
                    │    └──────────┬───────────┘
                    │               │
                    └───────────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │  Transform Payload     │
                │  Apply Mapping         │
                └───────────┬───────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │  Process Batch        │
                │  (Standard Flow)     │
                └───────────────────────┘
```

### 10.3 Componentes

#### A. Modelo `numa.synch.ai.map`

Almacena mapeos generados por IA para transformar payloads.

**Campos:**
- `remote_token`: Identificador del sistema remoto
- `model_name`: Nombre del modelo Odoo objetivo
- `mapping_json`: Diccionario JSON mapeando campos remotos a locales
- `transformation_script`: Script Python opcional para transformaciones complejas
- `confidence_score`: Score de confianza de la IA (0.0 a 1.0)
- `active`: Estado activo/inactivo

**Ejemplo de Mapping:**
```json
{
  "fname": "name",
  "email_addr": "email",
  "phone_num": "phone"
}
```

#### B. Modelo `numa.synch.issue`

Registra análisis de brechas cuando la IA no puede resolver automáticamente.

**Campos:**
- `batch_id`: Identificador del batch que generó el issue
- `remote_token`: Identificador del sistema remoto
- `model_name`: Nombre del modelo con el issue
- `issue_type`: Tipo de issue (missing_field, type_mismatch, ambiguity, other)
- `description`: Explicación de la IA sobre el problema
- `remote_field_sample`: Muestra de datos del payload para contexto
- `suggestion`: Sugerencia propuesta por la IA
- `confidence_score`: Score de confianza del análisis
- `resolved`: Flag de resolución manual

### 10.4 Flujo de Trabajo

#### Paso 1: Interceptar Falla de Validación

Cuando `_validate_metadata()` falla con `UserError`, el módulo intercepta la excepción y activa el flujo asistido por IA.

#### Paso 2: Verificar Cache

Busca en `numa.synch.ai.map` un mapeo activo para el `remote_token` y `model_name`:
- **Si existe**: Aplica el mapeo y continúa
- **Si no existe**: Procede al análisis de IA

#### Paso 3: Análisis de IA

Construye un prompt estructurado que incluye:
- **Esquema objetivo**: Estructura del modelo Odoo local
- **Esquema fuente**: Estructura del sistema remoto (inferido de metadata o muestras)
- **Instrucciones**: Mapear campos basándose en similitud semántica y compatibilidad de tipos

La IA retorna JSON con:
- `mapping`: Diccionario de mapeos de campos
- `confidence_score`: Score de confianza (0.0 a 1.0)
- `issues`: Lista de problemas detectados
- `critical_issues`: Boolean indicando si hay issues críticos

#### Paso 4: Decisión

**Alta Confianza (>0.9) + Sin Issues Críticos:**
- Crea registro en `numa.synch.ai.map`
- Aplica mapeo al payload
- Continúa con procesamiento estándar
- Log: "AI Mapping created for node X"

**Baja Confianza O Issues Críticos:**
- Crea registros en `numa.synch.issue` para cada problema
- Lanza `UserError` con mensaje descriptivo
- Aborta transacción
- Usuario debe revisar issues y resolver manualmente

#### Paso 5: Transformación de Payload

Si existe un mapeo cacheado:
1. Itera sobre registros del batch
2. Para cada registro, aplica el mapeo:
   - Renombra campos según `mapping_json`
   - Ejecuta `transformation_script` si existe
3. Pasa payload transformado al procesamiento estándar

### 10.5 Prompt Engineering

El prompt enviado a la IA está diseñado para:

1. **Actuar como Data Engineer**: Especializado en mapeo de esquemas
2. **Analizar Similitud Semántica**: No solo coincidencia de nombres
3. **Considerar Compatibilidad de Tipos**: string → char OK, integer → date NO
4. **Identificar Issues Críticos**: Campos requeridos faltantes, tipos incompatibles
5. **Proporcionar Scores Conservadores**: Ser cauteloso con la confianza
6. **Retornar JSON Estructurado**: Formato consistente para parsing

### 10.6 Casos de Uso

#### Caso 1: Sistema Externo con Nombres Diferentes

**Escenario:** Sistema CRM externo usa `customer_name`, Odoo espera `name`

**Solución:**
1. Primera sincronización: IA detecta y genera mapeo `{"customer_name": "name"}`
2. Mapeo se cachea
3. Sincronizaciones futuras usan mapeo cacheado automáticamente

#### Caso 2: Campos Faltantes

**Escenario:** Odoo requiere `is_company` pero sistema externo no lo provee

**Solución:**
1. IA detecta campo faltante
2. Issue es registrado con sugerencia
3. Usuario puede:
   - Agregar script de transformación con valor por defecto
   - Actualizar sistema fuente para proveer el campo

#### Caso 3: Transformación Compleja

**Escenario:** Sistema externo tiene `first_name` y `last_name` separados, Odoo tiene `name` único

**Solución:**
1. IA genera mapeo básico
2. Usuario agrega script de transformación:
   ```python
   if field_name == "name":
       result = f"{first_name} {last_name}".strip()
   ```

### 10.7 Ventajas

1. **Flexibilidad Máxima**: Permite sincronizar con cualquier sistema
2. **Automatización**: Reduce trabajo manual de mapeo
3. **Cache Inteligente**: Evita llamadas repetidas a IA
4. **Análisis Detallado**: Gap analysis ayuda a resolver problemas
5. **Transparente**: Integración seamless con flujo existente

### 10.8 Limitaciones

1. **Dependencia de IA**: Requiere `numa_ai` instalado y configurado
2. **Latencia Inicial**: Primera vez requiere análisis de IA (subsecuentes usan cache)
3. **Precisión**: Mapeos pueden necesitar revisión manual
4. **Threshold de Confianza**: Mapeos con confianza < 0.9 son rechazados

### 10.9 Mejores Prácticas

1. **Revisar Mapeos**: Después de creación automática, verificar y ajustar
2. **Monitorear Issues**: Revisar regularmente issues no resueltos
3. **Usar Scripts**: Para transformaciones complejas, usar transformation scripts
4. **Mantener Cache Limpio**: Desactivar mapeos no usados

---

**Versión del Análisis:** 3.0  
**Fecha:** 2024  
**Autor:** Análisis generado automáticamente  
**Última Actualización:** Incluye adaptación asistida por IA y configuración de frecuencia por conexión
