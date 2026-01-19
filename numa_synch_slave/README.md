# Numa Synch Slave - Nodo Branch

## Descripción

`numa_synch_slave` convierte una instancia de Odoo en un "Nodo Branch" (Slave) del sistema de sincronización. Ejecuta un trabajo programado para detectar cambios locales, serializarlos, enviarlos al Master vía HTTP, y procesar respuestas para actualizar mapeos locales.

## Características

- **Sincronización Programada**: Cron job cada 15 minutos (configurable)
- **Delta Detection**: Detecta solo registros modificados desde última sincronización
- **BFS Dependency Resolution**: Explora dependencias Many2one automáticamente
- **Batch Processing**: Procesa en lotes con commits atómicos
- **UUID Automático**: Genera token único para identificación
- **Connection Testing**: Prueba de conexión al Master
- **Manual Sync Trigger**: Sincronización manual desde la UI

## Instalación

```bash
# Desde el directorio de addons de Odoo
# Requiere: numa_synch
# External dependencies: requests (Python)
```

## Configuración

### 1. Crear Reglas de Sincronización

Ve a **Synchronization > Synchronization Rules** y crea reglas para los modelos que deseas sincronizar:

1. **Name**: Nombre descriptivo
2. **Model**: Selecciona el modelo
3. **Domain Filter**: Define qué registros sincronizar
4. **Direction**: `bidirectional` o `outgoing`
5. **Binary Fields**: Configura sincronización de campos binary si es necesario
6. **Computed Fields**: Configura sincronización de campos computados

### 2. Configurar Conexión al Master

Ve a **Synchronization > Slave Connections** y crea una nueva conexión:

1. **Name**: Nombre descriptivo (ej: "Central Server")
2. **Master URL**: URL base del Master (ej: `https://my-odoo.com`)
3. **Master Database**: Nombre de la base de datos en el Master
4. **API Key**: API Key generada en el Master
5. **Slave Token**: Se genera automáticamente (UUID único, no editable)
6. **Batch Size**: Tamaño de lote (default: 100, recomendado: 50-200)
7. **Active**: Activar/desactivar sincronización

### 3. Probar Conexión

1. Haz clic en el botón **"Test Connection"**
2. Verifica que la conexión sea exitosa
3. Si falla, revisa:
   - URL del Master
   - API Key
   - Conectividad de red

### 4. Ejecutar Sincronización Manual

1. Haz clic en el botón **"Run Sync Now"**
2. Monitorea los logs para ver el progreso
3. Verifica que `last_sync_date` se actualice

## Flujo de Sincronización

### 1. Discovery (Delta Detection)
- Obtiene reglas activas
- Para cada regla: busca registros modificados desde `last_sync_date`
- Usa `get_delta_domain()` para combinar filtros

### 2. Dependency Resolution (BFS)
- Explora dependencias Many2one de registros encontrados
- Agrega dependencias no mapeadas a la cola
- Continúa hasta agotar todas las dependencias

### 3. Serialization
- Serializa cada registro usando `_serialize_record()`
- Convierte Many2one a formato referencia
- Incluye campos binary si está configurado
- Incluye campos computados almacenados si está configurado

### 4. Batching & Transport
- Divide registros en lotes según `batch_size`
- Envía POST a `/numa_synch/api/v1/sync_batch`
- Headers: `Authorization: Bearer {api_key}`

### 5. Response Processing
- Si éxito: actualiza mappings con Master IDs
- Commit transaction por cada batch exitoso
- Si falla: rollback, no actualiza `last_sync_date`

### 6. Finalization
- Si todos los batches exitosos: actualiza `last_sync_date`
- Si algún batch falla: no actualiza `last_sync_date` (Time Safety)

## Cron Job

El cron job se ejecuta automáticamente cada 15 minutos y procesa todas las conexiones activas.

**Configuración del Cron**:
- **Model**: `numa.synch.connection`
- **Method**: `_cron_sync_all_connections()`
- **Interval**: 15 minutos
- **Active**: True

Para modificar el intervalo, edita el registro `ir.cron` en **Settings > Technical > Automation > Scheduled Actions**.

## Troubleshooting

### La sincronización no se ejecuta

1. Verifica que la conexión esté activa
2. Verifica que haya reglas de sincronización activas
3. Revisa los logs de Odoo para errores
4. Prueba la conexión manualmente

### Errores de autenticación

1. Verifica que el API Key sea correcto
2. Verifica que el API Key no haya expirado
3. Verifica permisos del usuario asociado al API Key

### Errores de red

1. Verifica conectividad al Master
2. Verifica que el Master URL sea correcto
3. Verifica firewall/proxy settings

### Campos binary no se sincronizan

1. Verifica que `sync_binary_fields` esté habilitado en la regla
2. Verifica que el tamaño del campo no exceda `binary_max_size_mb`
3. Revisa logs para ver si hay errores de compresión

### Campos computados no se recalculan

1. Verifica que `sync_computed_fields` esté habilitado en la regla
2. Verifica que `recalculate_computed` esté habilitado
3. Revisa logs para ver si hay errores en el recálculo

## Dependencias

- `numa_synch`
- `requests` (Python library)

## Licencia

LGPL-3

## Autor

Gustavo Marino <gamarino@numaes.com>
