# Numa FSM Pub/Sub

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Before the migration it
**did not install**: see [What was found](#what-was-found-before-migrating).

Event-driven architecture for FSM instances, through a pub/sub topology.

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
- A `system_ping` topic for diagnostics
- A `_handle_topic_system_ping()` handler that writes to chatter
- A Server Action "TEST: Enviar Ping a Suscriptores" for easy testing

## License

LGPL-3


---

## What was found before migrating

The module was written for 18.0 and never ran. Three things stopped the install outright,
each on its own:

1. **Its own data violated its own constraint.** The shipped topic was called
   `system.ping`, and `_check_name_format` rejects anything that is not alphanumeric plus
   underscores and hyphens. Loading the module's data failed.
2. **And had it loaded, the handler would never have been found.** The dispatcher builds
   a method name out of the topic — `_handle_topic_{topic}` — so `system.ping` asked for
   `_handle_topic_system.ping`, which no Python name can be. The handler shipped with the
   module was unreachable. Topic names are now normalised, dots included, and the lookup
   uses the normalised name.
3. **The server action imported a module.** `import datetime` inside an
   `ir.actions.server` body is a forbidden opcode under `safe_eval` (`IMPORT_NAME`), so
   the action could not even be loaded. `datetime` is already in the evaluation context.

And two that were quieter, but are the kind that corrupt data rather than stop a boot:

- **Neither unique constraint existed.** Both were declared with `_sql_constraints`,
  which Odoo 20 ignores with a warning (`model_classes.py:175`). So two topics could
  share a name — a publisher would find whichever came first — and an instance could
  subscribe to the same topic twice, which delivers every publication to it twice. They
  are `models.UniqueIndex` now.
- **Both subscription counters never refreshed.** They ran a `search_count` per record,
  one with `@api.depends('name')` — which is not what it reads — and the other with no
  `@api.depends` at all. They are computed over the one2many now, in one query.

The `is_active` constraint on subscriptions also did not depend on `is_active`, so
switching a subscription back on against a closed topic went through unchecked.

## Tests

```bash
odoo-bin -d <database> -u numa_fsm_pubsub --without-demo \
         --test-enable --test-tags=/numa_fsm_pubsub --stop-after-init
```

Nineteen tests, where there were none. Delivery is asynchronous by design, so they split
in two: the routing — who would be handed the message — is asserted on what `publish`
returns, and what the message does on arrival is asserted by calling `notify` directly,
which is exactly what the worker calls.

They cover topic names and their normalisation, both unique indexes, the counters, an
undeclared topic reaching nobody, an inactive topic reaching nobody, a payload that
cannot be serialised not stopping the publication, the handler being found under the
normalised name, the statistics being updated on arrival, a broken payload not breaking
the delivery, a failing handler not propagating to the publisher's job, and the fallback
to an FSM event when there is no handler.
