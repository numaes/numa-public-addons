# Numa Synch Master - Servidor Central

## Descripción

`numa_synch_master` convierte una instancia de Odoo en el "Servidor Central" (Master) del sistema de sincronización. Expone endpoints API para que los Slaves se conecten y procesa datos entrantes usando la estrategia "Two-Phase Write" para manejar dependencias circulares.

## Características

- **JSON-RPC API Endpoint**: `/numa_synch/api/v1/sync_batch`
- **Two-Phase Write Strategy**: Resuelve dependencias circulares
- **Last Write Wins (LWW)**: Resolución de conflictos basada en timestamps
- **Namespace Safety**: Solo modelos permitidos en reglas
- **Reference Safety**: Manejo graceful de referencias faltantes
- **Soporte Binary Fields**: Procesamiento de campos binary con descompresión
- **Soporte Computed Fields**: Recalculación automática de campos computados

## Instalación

```bash
# Desde el directorio de addons de Odoo
# Requiere: numa_synch, sale, stock, account
```

## Configuración

### 1. Crear Reglas de Sincronización

Ve a **Synchronization > Synchronization Rules** y crea reglas para los modelos que deseas sincronizar:

1. **Name**: Nombre descriptivo (ej: "Sync Partners")
2. **Model**: Selecciona el modelo (ej: `res.partner`)
3. **Domain Filter**: Define qué registros sincronizar (ej: `[('active', '=', True)]`)
4. **Direction**: `bidirectional` o `incoming`
5. **Binary Fields**: Configura si deseas sincronizar campos binary
6. **Computed Fields**: Configura si deseas sincronizar/recalcular campos computados

### 2. Generar API Key

1. Ve a **Settings > Users & Companies > API Keys**
2. Crea una nueva API Key para el usuario que usará el Slave
3. Copia el API Key (solo se muestra una vez)

### 3. Proporcionar Credenciales al Slave

El Slave necesitará:
- **Master URL**: URL base de tu instancia Odoo (ej: `https://my-odoo.com`)
- **Master Database**: Nombre de la base de datos
- **API Key**: La API Key generada

## API Endpoint

### POST `/numa_synch/api/v1/sync_batch`

**Autenticación**: Bearer Token (API Key)

**Request Body**:
```json
{
  "slave_token": "uuid-string",
  "records": [
    {
      "model": "res.partner",
      "local_id": 123,
      "vals": {
        "name": "Partner Name",
        "email": "partner@example.com",
        ...
      },
      "write_date": "2024-01-01T12:00:00"
    }
  ]
}
```

**Response**:
```json
{
  "status": "success",
  "message": "Processed 5 records",
  "updated_mappings": [
    {
      "model": "res.partner",
      "slave_id": 123,
      "master_id": 456
    }
  ]
}
```

## Two-Phase Write Strategy

### Phase 1: Skeleton Creation
- Crea registros con solo campos escalares
- Ignora relaciones (Many2one, x2many)
- Crea mappings inmediatamente

### Phase 2: Decoration
- Procesa campos relacionales
- Traduce referencias usando mappings de Phase 1
- Maneja referencias faltantes gracefully

## Last Write Wins (LWW)

Compara `write_date` entre Slave y Master:
- Si Slave es más nuevo → aplica cambios
- Si Master es más nuevo → ignora cambios y log en chatter

## Seguridad

- **Namespace Safety**: Solo modelos definidos en reglas pueden sincronizarse
- **Reference Safety**: Referencias faltantes no causan crashes
- **Authentication**: Bearer token requerido

## Dependencias

- `numa_synch`
- `sale`
- `stock`
- `account`

## Licencia

LGPL-3

## Autor

Gustavo Marino <gamarino@numaes.com>
