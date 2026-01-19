# Guía de Usuario - Numa Synch

## Introducción

Numa Synch es un sistema de sincronización offline-first para Odoo que permite mantener múltiples instancias sincronizadas en una arquitectura Master-Slave.

## Conceptos Básicos

### Master (Servidor Central)
- Instancia central que recibe datos de múltiples Slaves
- Almacena la "verdad única" de los datos
- Procesa cambios usando estrategia Two-Phase Write

### Slave (Nodo Branch)
- Instancia que envía cambios al Master
- Funciona offline y sincroniza cuando hay conexión
- Detecta cambios automáticamente

### Identity Mapping
- Tabla que mapea IDs locales a IDs remotos
- Permite traducir referencias entre sistemas
- Se actualiza automáticamente durante la sincronización

### Synchronization Rules
- Define qué registros sincronizar
- Permite filtros complejos usando dominios de Odoo
- Configura dirección de sincronización

## Configuración Inicial

### En el Master

1. **Instalar módulo**: `numa_synch_master`
2. **Crear reglas de sincronización**:
   - Ve a **Synchronization > Synchronization Rules**
   - Crea reglas para cada modelo que deseas sincronizar
   - Configura filtros de dominio si es necesario
   - Establece dirección: `bidirectional` o `incoming`

3. **Generar API Key**:
   - Ve a **Settings > Users & Companies > API Keys**
   - Crea una nueva API Key
   - **Importante**: Copia el API Key inmediatamente (solo se muestra una vez)

### En el Slave

1. **Instalar módulo**: `numa_synch_slave`
2. **Crear reglas de sincronización**:
   - Ve a **Synchronization > Synchronization Rules**
   - Crea reglas para cada modelo que deseas sincronizar
   - Establece dirección: `bidirectional` o `outgoing`

3. **Configurar conexión al Master**:
   - Ve a **Synchronization > Slave Connections**
   - Crea una nueva conexión
   - Completa:
     - **Name**: Nombre descriptivo
     - **Master URL**: URL del Master (ej: `https://my-odoo.com`)
     - **Master Database**: Nombre de la base de datos
     - **API Key**: API Key generada en el Master
     - **Batch Size**: Tamaño de lote (default: 100)
   - **Slave Token**: Se genera automáticamente (no editable)

4. **Probar conexión**:
   - Haz clic en **"Test Connection"**
   - Verifica que sea exitosa

## Uso Diario

### Sincronización Automática

La sincronización se ejecuta automáticamente cada 15 minutos. No requiere intervención manual.

### Sincronización Manual

1. Ve a **Synchronization > Slave Connections**
2. Selecciona la conexión
3. Haz clic en **"Run Sync Now"**
4. Monitorea el progreso en los logs

### Verificar Estado de Sincronización

1. Ve a **Synchronization > Identity Mapping**
2. Filtra por modelo o nodo
3. Verifica que los mappings estén actualizados

### Verificar Última Sincronización

1. Ve a **Synchronization > Slave Connections**
2. Revisa el campo **"Last Sync Date"**
3. Si no se actualiza, revisa los logs para errores

## Configuración Avanzada

### Campos Binary

Para sincronizar campos binary (archivos adjuntos, imágenes):

1. Edita la regla de sincronización
2. Habilita **"Sync Binary Fields"**
3. Configura:
   - **Max Binary Size (MB)**: Tamaño máximo (default: 10 MB)
   - **Compress Binary Fields**: Comprimir antes de enviar (recomendado)

**Nota**: Sincronizar campos binary aumenta significativamente el tamaño del payload y el tiempo de transferencia.

### Campos Computados

Para sincronizar campos computados:

1. Edita la regla de sincronización
2. Habilita **"Sync Computed Fields"**
3. Configura:
   - **Recalculate Non-Stored Computed**: Recalcular campos computados no almacenados en destino

**Nota**: Recalcular campos computados puede tener impacto en performance, especialmente para cálculos complejos.

### Filtros de Dominio

Usa filtros de dominio para sincronizar solo registros específicos:

**Ejemplos**:
- Solo activos: `[('active', '=', True)]`
- Solo confirmados: `[('state', '=', 'confirmed')]`
- Combinado: `[('active', '=', True), ('state', '=', 'done')]`

### Tamaño de Lote

Ajusta el tamaño de lote según tu ancho de banda:
- **Conexión rápida**: 200-500 registros
- **Conexión media**: 100-200 registros
- **Conexión lenta**: 50-100 registros

## Resolución de Problemas

### La sincronización no funciona

1. Verifica que las reglas estén activas
2. Verifica que la conexión esté activa
3. Revisa los logs de Odoo
4. Prueba la conexión manualmente

### Errores de autenticación

1. Verifica que el API Key sea correcto
2. Regenera el API Key si es necesario
3. Verifica permisos del usuario

### Campos no se sincronizan

1. Verifica que el modelo esté en una regla activa
2. Verifica que el registro cumpla el filtro de dominio
3. Verifica que la dirección de sincronización sea correcta

### Referencias rotas

1. Verifica que las dependencias estén sincronizadas primero
2. Revisa el Identity Mapping para verificar mappings
3. Ejecuta sincronización manual para forzar dependencias

## Mejores Prácticas

1. **Orden de sincronización**: Sincroniza dependencias primero (ej: partners antes de sales orders)
2. **Filtros específicos**: Usa filtros de dominio para sincronizar solo lo necesario
3. **Monitoreo**: Revisa regularmente el Identity Mapping y los logs
4. **Backup**: Haz backup antes de cambios importantes
5. **Testing**: Prueba en ambiente de desarrollo antes de producción

## Limitaciones

- **Sincronización unidireccional**: Actualmente solo Slave → Master
- **Last Write Wins**: Puede perder cambios en ediciones simultáneas
- **Campos binary**: Requieren configuración explícita y aumentan payload
- **Campos computados**: Recalcular puede ser costoso en performance

## Soporte

Para soporte técnico, contacta a:
- **Email**: gamarino@numaes.com
- **Website**: https://www.numaes.com
