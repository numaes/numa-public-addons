# Instrucciones de Prueba Manual - Sistema Pub/Sub FSM

Este documento describe cómo probar manualmente el circuito completo de pub/sub entre instancias FSM.

## Objetivo de la Prueba

Validar que:
1. ✅ El despacho dinámico `_handle_topic_{topic}` funciona correctamente
2. ✅ El `message_post` ocurre en una transacción separada (si async está activo)
3. ✅ La comunicación asíncrona entre FSMs funciona end-to-end

## Prerequisitos

- Módulo `numa_fsm_pubsub` instalado
- Módulo `numa_fsm` instalado y funcionando
- Módulo `numa_asynch_exec` instalado (para ejecución asíncrona)
- Al menos una FSM Definition creada

## Pasos de Configuración

### Paso 1: Crear FSM "Emisor"

1. Ir a **FSM > Definitions** (o la ruta equivalente en tu menú)
2. Seleccionar o crear una FSM Definition
3. Crear una nueva **FSM Instance**:
   - Nombre: "Emisor" (o cualquier nombre descriptivo)
   - Definition: Seleccionar la FSM Definition
   - Estado: Puede estar en cualquier estado (init, running, paused)
4. **Guardar** la instancia
5. **Anotar el ID** de la instancia (aparece en la URL o en el campo `name`)

### Paso 2: Crear FSM "Receptor"

1. Crear otra **FSM Instance**:
   - Nombre: "Receptor" (o cualquier nombre descriptivo)
   - Definition: Puede ser la misma o diferente
   - Estado: Puede estar en cualquier estado
2. **Guardar** la instancia
3. **Anotar el ID** de la instancia

### Paso 3: Crear la Suscripción

1. Ir a **FSM Pub/Sub > Subscriptions** (o buscar "numa.fsm.subscription" en el menú técnico)
2. Crear una nueva **Subscription**:
   - **Topic**: Seleccionar `system.ping` (debería aparecer en la lista)
   - **Subscriber FSM Instance**: Seleccionar la FSM "Receptor" creada en el Paso 2
   - **Active**: ✅ Marcado (activo)
3. **Guardar** la suscripción

**Verificación**: Deberías ver que la suscripción se creó correctamente y está activa.

### Paso 4: Ejecutar la Server Action en el Emisor

1. Abrir la FSM Instance **"Emisor"** creada en el Paso 1
2. En el formulario, buscar el menú **"Action"** (o el menú contextual)
3. Seleccionar **"TEST: Enviar Ping a Suscriptores"**
4. La acción se ejecutará y deberías ver un mensaje de confirmación

**Nota**: Si no ves la acción en el menú, verifica que:
- El módulo `numa_fsm_pubsub` esté instalado correctamente
- La acción esté activa (ir a **Settings > Technical > Actions > Server Actions**)

### Paso 5: Verificar Chatter del Receptor

1. Abrir la FSM Instance **"Receptor"** creada en el Paso 2
2. Ir a la pestaña **"Chatter"** (parte inferior del formulario)
3. **Buscar el mensaje más reciente**

**Resultado Esperado**:
```
🏓 PONG recibido desde [Nombre del Emisor]!
Timestamp: [Fecha y hora]
{
  "sender": "[Nombre del Emisor]",
  "timestamp": "[Fecha y hora]",
  "fsm_id": [ID],
  "fsm_name": "[Nombre]"
}
```

## Validación de Resultados

### ✅ Caso Exitoso

Si ves el mensaje "🏓 PONG recibido" en el chatter del Receptor:
- ✅ El tópico `system.ping` fue encontrado
- ✅ La suscripción funcionó correctamente
- ✅ El método `publish()` entregó el mensaje
- ✅ El dispatcher dinámico encontró `_handle_topic_system_ping()`
- ✅ El handler ejecutó correctamente
- ✅ El `message_post` se realizó en el Receptor

### ⚠️ Verificaciones Adicionales

#### Verificar Ejecución Asíncrona

1. Ir a **Settings > Technical > Asynchronous Jobs** (si existe en `numa_asynch_exec`)
2. Buscar jobs recientes relacionados con `notify`
3. Verificar que el job se ejecutó correctamente

**Nota**: Si no hay jobs asíncronos visibles, verifica la configuración de `numa_asynch_exec`.

#### Verificar Logs

1. Revisar los logs del servidor Odoo
2. Buscar mensajes que contengan:
   - `"Published to topic 'system.ping'"`
   - `"FSM Instance X: PONG recibido"`
   - `"Enqueued notification"`

#### Verificar Estadísticas de Suscripción

1. Ir a la **Subscription** creada en el Paso 3
2. Verificar que:
   - `Last Notification Date` se actualizó
   - `Notifications Count` incrementó

## Casos de Prueba Adicionales

### Prueba 2: Múltiples Suscriptores

1. Crear una tercera FSM Instance "Receptor 2"
2. Crear otra suscripción para "Receptor 2" al tópico `system.ping`
3. Ejecutar la Server Action en el Emisor
4. Verificar que **ambos** receptores recibieron el mensaje

### Prueba 3: Suscripción Inactiva

1. Desactivar la suscripción (marcar `Active` como ❌)
2. Ejecutar la Server Action en el Emisor
3. Verificar que el Receptor **NO** recibió el mensaje

### Prueba 4: Tópico Inexistente

1. Modificar la Server Action para publicar a un tópico que no existe (ej: `nonexistent.topic`)
2. Ejecutar la acción
3. Verificar que no se rompe el sistema (debería loguear un warning)

### Prueba 5: Payload Complejo

1. Modificar la Server Action para enviar un payload más complejo:
```python
payload = {
    'sender': record.display_name,
    'timestamp': str(datetime.datetime.now()),
    'data': {
        'order_id': 123,
        'amount': 1000.0,
        'items': ['item1', 'item2']
    }
}
```
2. Verificar que el payload completo aparece en el chatter del Receptor

## Troubleshooting

### Problema: No aparece la Server Action

**Solución**:
1. Ir a **Settings > Technical > Actions > Server Actions**
2. Buscar "TEST: Enviar Ping a Suscriptores"
3. Verificar que está activa y vinculada al modelo `fsm.instance`
4. Si no existe, reinstalar el módulo `numa_fsm_pubsub`

### Problema: El Receptor no recibe el mensaje

**Verificaciones**:
1. ✅ La suscripción está activa (`is_active = True`)
2. ✅ El tópico `system.ping` existe y está activo
3. ✅ El Receptor tiene el método `_handle_topic_system_ping()` (debería estar en el código)
4. ✅ Revisar logs del servidor para errores
5. ✅ Verificar que `numa_asynch_exec` está funcionando

### Problema: El mensaje aparece inmediatamente (no asíncrono)

**Explicación**:
- Si `numa_asynch_exec` no está configurado correctamente, puede ejecutarse de forma síncrona
- Esto es aceptable para pruebas, pero en producción debería ser asíncrono
- Verificar configuración de `numa_asynch_exec`

### Problema: Error en el handler

**Solución**:
1. Revisar logs del servidor para el error específico
2. Verificar que el payload tiene el formato esperado
3. El handler debería manejar errores gracefully (no romper el thread principal)

## Notas Técnicas

### Ejecución Asíncrona

El método `publish()` utiliza `asynch_exec()` para entregar mensajes de forma asíncrona:

```python
subscriber.asynch_exec().notify(normalized_name, payload_str)
```

Esto significa que:
- El `publish()` retorna inmediatamente
- El `notify()` se ejecuta en un thread separado
- El `message_post` ocurre en una transacción separada

### Dispatcher Dinámico

El método `notify()` busca dinámicamente handlers con el patrón:
```python
handler_method_name = f'_handle_topic_{topic_name}'
handler_method = getattr(self, handler_method_name, None)
```

Si el handler existe, se ejecuta. Si no, intenta disparar un evento FSM.

### Schema-on-Read

El sistema sigue la filosofía "Schema-on-Read":
- No valida el payload en `publish()`
- No falla si el tópico no existe (solo loguea)
- La validación ocurre en el handler específico

## Conclusión

Si todas las pruebas pasan, el sistema pub/sub está funcionando correctamente y listo para uso en producción.

---

**Fecha de Creación**: 2024  
**Módulo**: `numa_fsm_pubsub`  
**Versión**: 18.0.1.0.0
