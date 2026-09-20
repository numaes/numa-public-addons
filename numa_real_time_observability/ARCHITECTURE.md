# Architecture: NUMA Real-Time Observability

This document describes the internal design and data flow of the **numa_real_time_observability** addon for developers and maintainers.

---

## 1. Component Overview

| Component | Path | Role |
|-----------|------|------|
| Manifest | `__manifest__.py` | Module metadata, dependencies (`base`, `bus`), and security data. |
| Mixin | `models/real_time_observability_mixin.py` | Abstract model providing `real_time_notify()` and JSON validation. |
| Security | `security/security.xml` | Placeholder for security rules; no record rules required for the abstract mixin. |

The addon does not define concrete models or views; it only provides the mixin and its behaviour.

---

## 2. Data Flow

### 2.1 Sequence

```
[Caller]  real_time_notify(notification_data, condition)
    |
    v
[Mixin]   Validate notification_data (JSON-serializable)
    |
    v
[Mixin]   For each record in self (with id, and condition(record) if condition given):
    |        - Build message = { id, notification_data }
    |        - Register env.cr.postcommit.add(_send_notification)
    v
[Caller]  Transaction continues and commits
    |
    v
[Odoo]    Post-commit hooks run (new cursor, same DB)
    |
    v
[Mixin]   _send_notification():
    |        - Obtain registry and new env
    |        - Check record still exists
    |        - bus.bus._sendone(<observer group record>, "observability/<model_name>", payload)
    |        - cr.commit()
    v
[Bus]     Message delivered to all subscribers of the channel
```

### 2.2 Why post-commit?

Notifications are deferred until after commit so that:

1. **Consistency:** Subscribers only see events for data that has been persisted.
2. **No side effects in transaction:** Bus I/O and any subscriber-side work do not run inside the same transaction that wrote the data.
3. **Rollback safety:** If the main transaction is rolled back, no notification is sent.

---

## 3. Design Decisions

### 3.1 Abstract model

The mixin is an `AbstractModel` (`_name = 'real.time.observability.mixin'`). It is not meant to be instantiated as a standalone model; it only adds behaviour to models that inherit from it. No tables or direct access rights are required.

### 3.2 One notification per record

When `real_time_notify()` is called on a recordset, one notification is scheduled per record (each with the same `notification_data`). This keeps the contract simple and allows listeners to correlate by record `id`. Aggregation or batching can be implemented in calling code (e.g. send a single “batch” event from one representative record).

### 3.3 Channel naming

The channel is the **Real-Time Observer group record**, because Odoo lets a
client subscribe to any *string* channel it asks for: a string channel named
after the model would be readable by anyone with a websocket. A record channel
is only reachable through `ir.websocket._build_bus_channel_list`, which adds a
user's own groups and nothing else, so membership is the access control.

The model name lives in the notification type, `observability/<model_name>`,
which is what `busService.subscribe()` filters on. One channel, one type per
model.

### 3.4 New cursor in post-commit

There is no hook and no second cursor: `bus.bus._sendone()` is called in the
current transaction, and `bus.bus` does the deferring itself. It writes its
rows in a **precommit** hook and issues the PostgreSQL `NOTIFY` in a
**postcommit** one, so a subscriber is told only about data that committed. The
module used to wrap this in a hook and a cursor of its own, which bought
nothing and hid a late-binding bug that made every notification of a recordset
carry the last record's id.

### 3.5 Error handling

Exceptions during validation (e.g. non-JSON-serializable data) or during the post-commit send are logged and do not propagate to the caller or the main transaction. The mixin is designed to fail softly so that observability does not break core business flows.

---

## 4. Dependencies

- **base:** Required for Odoo models and environment.
- **bus:** Required for `bus.bus` and `_sendone()` to deliver messages to channels, and for `ir.websocket`, which is what puts a group's members on its channel.

No other addons are required.

---

## 5. Extension Points

- **New channels:** the channel is always the observer group. A model that needs
  a narrower audience has to override `real_time_notify` and pass its own
  channel record. The notification type is fixed at `observability/<model_name>`.
- **Payload shape:** override `_observability_payload(record, notification_data)`.
- **Filtering:** Filtering is done via the `condition` parameter and/or by the payload (`notification_data`) that callers attach. The mixin does not add its own filters.
- **Backend consumption:** The addon only sends messages; it does not implement a bus listener. Backend subscribers must be implemented in separate code (e.g. cron, worker, or bus listener service) that subscribes to the same channels.

---

## 6. Testing Considerations

- Unit tests that call `real_time_notify()` should run inside a transaction that is committed (or use a test that commits and then checks bus or listener state); otherwise the post-commit hook never runs and no message is sent.
- Read the `bus.bus` rows after flushing the cursor, which is what the suite in
  `numa_real_time_observability_test` does: it asserts the channel, the type and
  the payload without mocking anything. Three of its tests go further and open a
  real websocket, since the access control lives in the subscription, not in the
  mixin.
- Test with records that have no `id` (e.g. new in-memory records) to ensure no notification is scheduled and a warning is logged.
- Test with non-serializable `notification_data` to ensure the call returns without raising and an error is logged.

---

## 7. Version and Compatibility

- **Module version:** 18.0.0.0  
- **Target Odoo:** 18.0  
- **Registry and post-commit API:** Aligned with Odoo 18.0; changes in `odoo.addons.bus` or in the registry/cursor lifecycle in future Odoo versions may require adjustments.
