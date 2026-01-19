# Análisis del Sistema de Sincronización Numa Synch

## Resumen Ejecutivo

El sistema **Numa Synch** es una solución de sincronización offline-first para Odoo 18.0 que permite mantener múltiples instancias de Odoo sincronizadas en una arquitectura Master-Slave. El sistema está compuesto por tres módulos modulares que trabajan en conjunto:

1. **`numa_synch`** - Módulo core (biblioteca base)
2. **`numa_synch_master`** - Servidor central (Master)
3. **`numa_synch_slave`** - Nodos branch (Slave)

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

#### C. `numa_synch_slave` (Branch Node)
**Propósito:** Nodo branch que detecta cambios locales y los envía al Master.

**Componentes:**
- **Connection Model**: Configuración de conexión al Master
- **Engine Slave**: Lógica de detección y envío
- **Cron Job**: Sincronización programada (15 minutos)

**Características:**
- Delta detection basado en `write_date`
- BFS exploration para dependencias Many2one
- Batch processing con commits atómicos
- UUID automático para identificación única

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
│     - Ignorar Binary fields (performance)                   │
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
- `_serialize_record(record)`: Serializa un registro a dict
  - Many2one → `{'__type__': 'ref', 'model': '...', 'id': ...}`
  - Date/Datetime → strings ISO
  - Binary → skip (performance)
  - Retorna: `(vals_dict, dependencies_list)`

- `_parse_incoming_ref(ref_dict, source_node)`: Parsea referencia entrante
  - Busca mapping usando `numa.synch.map`
  - Retorna: `local_id` o `False`

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

#### C. No hay sincronización de campos Binary
- **Problema**: Campos binarios se ignoran por performance
- **Impacto**: Archivos adjuntos no se sincronizan
- **Solución futura**: Sincronización opcional de binary con compresión

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

#### F. Validación de Datos
- Validar datos antes de aplicar
- Rollback automático en caso de errores de validación

#### G. Soporte para Campos Computados
- Sincronizar campos computados almacenados
- Recalcular campos computados en destino

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
- **Actual**: Validación básica
- **Mejora**: Validación estricta de tipos, constraints

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

### Áreas de Mejora:
1. ⚠️ Sincronización bidireccional completa
2. ⚠️ Manejo de eliminaciones
3. ✅ Sincronización de campos binary (IMPLEMENTADO)
4. ⚠️ Conflict resolution más avanzado
5. ⚠️ Métricas y monitoreo
6. ✅ Soporte para campos computados (IMPLEMENTADO)

### Recomendación:
El sistema está listo para uso en producción para casos de uso de sincronización unidireccional (Slave → Master). Para sincronización bidireccional completa, se recomienda implementar las mejoras sugeridas.

---

**Versión del Análisis:** 1.0  
**Fecha:** 2024  
**Autor:** Análisis generado automáticamente
