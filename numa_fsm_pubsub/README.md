# Numa FSM Pub/Sub

Event-Driven Architecture for FSM Instances using Pub/Sub pattern.

## Overview

This module transforms Odoo from a monolithic passive system to a reactive event-driven architecture, allowing FSM instances to communicate asynchronously and decoupled using the Actor Model and Pub/Sub pattern.

## Key Concepts

### Actor Model
Each `fsm.instance` acts as an "Actor" with:
- **Identity**: The FSM instance itself
- **State**: The current state of the FSM
- **Message Inbox**: The `notify()` method

### Pub/Sub Topology
Actors don't call each other directly. Instead:
- **Publishers** send messages to **Topics**
- **Subscribers** receive notifications from Topics they're subscribed to
- Communication is **asynchronous** and **decoupled**

### Schema-on-Read Philosophy
- **"Dumb Pipes, Smart Endpoints"**: The transport mechanism doesn't validate data
- Validation occurs at the receiving end
- Topics define the "contract" for documentation and AI context, not for strict runtime validation

## Architecture

### Models

#### `numa.fsm.topic`
Defines the semantic "Contract" of an event:
- `name`: Unique identifier (e.g., `sale_order_confirmed`)
- `description`: Human-readable description (also for RAG)
- `payload_example`: Example JSON structure (for documentation)

#### `numa.fsm.subscription`
Defines the wiring (cableado) of the graph:
- `topic_id`: The topic being subscribed to
- `subscriber_fsm_id`: The FSM instance that listens
- `is_active`: Whether the subscription is active

### Methods

#### `publish(topic_name, payload)`
Publishes an event to a topic:
1. Normalizes the topic name
2. Finds all active subscribers
3. Asynchronously delivers the message to each subscriber using `numa_asynch_exec`

#### `notify(topic_name, payload_str)`
The Actor's inbox/router (Single Entry Point):
1. Logs the arrival of the message
2. Tries to find a topic-specific handler: `_handle_topic_{topic_name}`
3. If handler exists, executes it with the payload
4. Falls back to triggering an FSM event/transition
5. Robust error handling (doesn't break main thread)

## Usage Examples

### Publishing an Event

```python
# In any FSM instance
fsm_instance = self.env['fsm.instance'].browse(123)
fsm_instance.publish('sale_order_confirmed', {
    'order_id': 456,
    'amount': 1000.0,
    'customer_id': 789
})
```

### Subscribing to a Topic

```python
# Create a subscription
self.env['numa.fsm.subscription'].create({
    'topic_id': self.env.ref('numa_fsm_pubsub.topic_test_ping').id,
    'subscriber_fsm_id': fsm_instance.id,
    'is_active': True,
})
```

### Implementing a Topic Handler

```python
def _handle_topic_sale_order_confirmed(self, payload):
    """Handle sale order confirmation events."""
    self.ensure_one()
    order_id = payload.get('order_id')
    # Process the event...
    self.message_post(body=f"Sale order {order_id} confirmed!")
    return True
```

### Test Ping Example

The module includes a `test_ping` topic and handler for testing:

```python
# Subscribe FSM instance to test_ping
subscription = self.env['numa.fsm.subscription'].create({
    'topic_id': self.env.ref('numa_fsm_pubsub.topic_test_ping').id,
    'subscriber_fsm_id': fsm_instance.id,
    'is_active': True,
})

# Publish a ping
another_fsm.publish('test_ping', {'message': 'Hello!'})

# The subscriber will receive "Pong recibido" in its chatter
```

## Dependencies

- `numa_fsm`: FSM engine
- `numa_asynch_exec`: Asynchronous execution infrastructure
- `mail`: For chatter integration

## Testing

See [TESTING_INSTRUCTIONS.md](TESTING_INSTRUCTIONS.md) for detailed manual testing instructions.

The module includes:
- A `system.ping` topic for diagnostics
- A `_handle_topic_system_ping()` handler that writes to chatter
- A Server Action "TEST: Enviar Ping a Suscriptores" for easy testing

## License

LGPL-3
