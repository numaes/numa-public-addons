# Numa Synch - Core Module

## Descripción

`numa_synch` es el módulo core del sistema de sincronización offline-first para Odoo 18.0. Proporciona la infraestructura base sin dependencias de red o cron jobs, actuando como biblioteca para los módulos `numa_synch_master` y `numa_synch_slave`.

## Características

- **Identity Mapping**: Tabla de alto rendimiento para mapear IDs locales a remotos
- **Synchronization Rules**: Reglas configurables con filtros de dominio
- **Abstract Serialization Engine**: Motor abstracto para serialización de registros
- **Soporte para campos Binary**: Sincronización opcional con compresión
- **Soporte para campos Computados**: Sincronización y recalculación automática

## Instalación

```bash
# Desde el directorio de addons de Odoo
# El módulo se instala automáticamente como dependencia de numa_synch_master o numa_synch_slave
```

## Componentes Principales

### 1. Identity Mapping (`numa.synch.map`)

Tabla de mapeo entre IDs locales y remotos para diferentes modelos y nodos.

**Campos:**
- `model_id`: Referencia al modelo
- `model_name`: Nombre técnico del modelo (indexado)
- `local_id`: ID en la base de datos local (indexado)
- `remote_id`: ID en la base de datos remota (indexado)
- `node_token`: Identificador del nodo remoto (indexado)
- `last_sync_date`: Timestamp de última sincronización

**Métodos:**
- `get_remote_id(model_name, local_id, node_token)`: Obtener ID remoto
- `get_local_id(model_name, remote_id, node_token)`: Obtener ID local
- `set_mapping(...)`: Crear/actualizar mapping (idempotente)

### 2. Synchronization Rules (`numa.synch.rule`)

Define qué registros sincronizar y en qué dirección.

**Campos:**
- `name`: Nombre descriptivo
- `model_id`: Modelo a sincronizar
- `domain_filter`: Filtro de dominio (widget domain)
- `direction`: bidirectional, outgoing, incoming
- `active`: Activar/desactivar
- `sync_binary_fields`: Sincronizar campos binary
- `binary_max_size_mb`: Tamaño máximo en MB (default: 10)
- `binary_compress`: Comprimir campos binary (default: True)
- `sync_computed_fields`: Sincronizar campos computados (default: True)
- `recalculate_computed`: Recalcular campos computados no almacenados (default: True)

**Métodos:**
- `get_delta_domain(last_sync_date)`: Combina dominio usuario + filtro write_date

### 3. Abstract Engine (`numa.synch.engine`)

Motor abstracto para serialización de registros.

**Métodos:**
- `_serialize_record(record, sync_rule=None)`: Serializa un registro
- `_parse_incoming_ref(ref_dict, source_node)`: Parsea referencias entrantes
- `_serialize_binary_field(...)`: Serializa campos binary
- `_deserialize_binary_field(...)`: Deserializa campos binary

## Uso

Este módulo no se usa directamente, sino como dependencia de:
- `numa_synch_master`: Para el servidor central
- `numa_synch_slave`: Para nodos branch

## Dependencias

- `base`
- `mail`
- `web`

## Licencia

LGPL-3

## Autor

Gustavo Marino <gamarino@numaes.com>
