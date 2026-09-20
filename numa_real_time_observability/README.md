# NUMA Real-Time Observability

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). The bus channel
changed, for a reason worth reading: see
[Migration to Odoo 20.0](#8-migration-to-odoo-200).

---

## 1. Overview

**NUMA Real-Time Observability** is an Odoo addon that provides a reusable mixin for publishing real-time events from any model via the Odoo bus. It enables server-side and client-side subscribers to react to model changes and business events without polling.

The addon introduces the abstract model `real.time.observability.mixin`. Any model that inherits from this mixin gains the method `real_time_notify()`, which publishes a bus notification that reaches subscribers **only once the transaction commits**, so nobody is told about data that was rolled back.

### 1.1 Key Features

| Feature | Description |
|--------|-------------|
| **Mixin-based integration** | Apply to any Odoo model with a single inheritance line. |
| **Post-commit delivery** | Notifications are sent only after a successful database commit. |
| **Model-scoped notification types** | Each model publishes under `observability/<model_name>`, which is what a client subscribes to. |
| **The group is the channel** | Messages go to the `Real-Time Observer` group, so only its members can reach them. |
| **Custom payloads** | Attach arbitrary, JSON-serializable data to each notification. |
| **Conditional notifications** | Optional callable to send notifications only when conditions are met. |
| **Error isolation** | Failures in notification delivery do not affect the main transaction. |
| **Dual consumption** | Events can be consumed from Python (backend) and JavaScript (frontend). |

### 1.2 Compatibility

- **Odoo version:** 20.0  
- **Dependencies:** `bus`  
- **License:** LGPL-3  

### 1.3 Who receives the notifications

Everything published by the mixin goes to the **Real-Time Observer** group
(`numa_real_time_observability.group_observer`), which is implied by
`base.group_system`. Odoo subscribes every user to the channels of their own
groups, so a member receives the notifications without writing a line of
subscription code, and a user outside the group cannot reach them at all.

Grant that group to whoever should watch; it carries no other right.

---

## 2. Installation

1. Place the `numa_real_time_observability` module in your Odoo addons path.
2. Update the application list (e.g. Apps → Update Apps List).
3. Install **NUMA Real-Time Observability** from the Apps menu.

No additional configuration is required. Security is defined in `security/security.xml` (no record rules are required for the abstract mixin).

---

## 3. Quick Start

### 3.1 Enabling observability on a model

Inherit from `real.time.observability.mixin` and call `real_time_notify()` after relevant operations:

```python
from odoo import models, fields

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'real.time.observability.mixin']

    def action_confirm(self):
        result = super().action_confirm()
        self.real_time_notify({
            'event': 'order_confirmed',
            'state': self.state,
            'amount_total': float(self.amount_total),
        })
        return result
```

### 3.2 Subscribing on the frontend (JavaScript)

The bus service subscribes by **notification type**, which is where the model
name travels. Nothing else is needed: a member of the observer group is already
on the channel.

```javascript
import { useService } from "@web/core/utils/hooks";

const bus = useService("bus_service");
bus.subscribe("observability/sale.order", ({ id, model, notification_data }) => {
    if (notification_data.event === "order_confirmed") {
        // Update UI, refresh data, or show a notification
    }
});
```

### 3.3 Subscribing on the backend (Python)

Consumption on the backend depends on your bus listener implementation. Read
the rows of `bus.bus` whose `channel` is the observer group, or attach to the
websocket the same way the client does.

---

## 4. API Reference

### 4.1 Method: `real_time_notify(notification_data=False, condition=None)`

Schedules a bus notification to be sent after the current transaction is committed successfully. Supports recordsets; one notification per record is scheduled (subject to optional `condition`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `notification_data` | `dict` or `False` | No | Payload to attach to the notification. Must be JSON-serializable. Default: `{}`. |
| `condition` | `callable(record) -> bool` | No | If provided, the notification is sent only for records for which `condition(record)` is truthy. |

**Returns:** the number of notifications published.

**Behaviour:**

- Records without an ID (e.g. new, unsaved) are skipped; a warning is logged.
- If `notification_data` is not a dict, it is wrapped as `{'data': notification_data}`; it must still be JSON-serializable.
- If serialization fails, an error is logged and **nothing at all** is published, not even for the records that would have been fine.
- A `condition` that raises skips that record only, with a warning.
- The message is written in the current transaction and the bus signals it after the commit, so a rollback notifies nobody.

### 4.2 Channel and message format

- **Channel:** the `Real-Time Observer` group record, not a string.
- **Notification type:** `observability/<model_name>` (e.g. `observability/sale.order`).
- **Message body:**

```json
{
    "id": <integer record id>,
    "model": "<model name>",
    "notification_data": { ... }
}
```

`notification_data` is the same dict passed to `real_time_notify()` (or its wrapped form).

Override `_observability_payload(record, notification_data)` to change what
subscribers receive.

---

## 5. Architecture Summary

1. **Call:** The model calls `real_time_notify(notification_data, condition)`.
2. **Validation:** The mixin checks that `notification_data` is a JSON-serializable dict; if it is not, nothing is published.
3. **Publication:** For each qualifying record, `bus.bus._sendone(observer_group, 'observability/<model>', payload)` is called in the **current** transaction.
4. **Commit:** `bus.bus` writes its rows in a precommit hook and signals PostgreSQL in a postcommit one, so subscribers hear about the change only once it is durable. A rollback notifies nobody.
5. **Consumption:** Members of the observer group, who are on that channel by virtue of their group, receive the message and filter it by notification type.

For implementation details, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 6. Best Practices

- **Payload size:** Keep `notification_data` small; subscribers can load full records if needed.
- **Event naming:** Use clear, consistent event names (e.g. `order_confirmed`, `task_completed`).
- **Context:** Include IDs and minimal context (e.g. state, type) so listeners can act without extra queries when possible.
- **Conditions:** Use the `condition` parameter to avoid sending notifications that no subscriber needs.
- **Testing:** `bus.bus` writes its rows in a precommit hook, so a test has to flush the cursor before the rows exist. See the suite in `numa_real_time_observability_test`.
- **Access:** the observer group carries no right other than hearing these notifications, so it can be granted narrowly. Do not publish anything a member should not see.

---

## 7. Troubleshooting

| Issue | Checks |
|-------|--------|
| No notifications received | Check that the user is in the **Real-Time Observer** group: the group is the channel. Then confirm the client subscribes to the notification type `observability/<model_name>`, that the transaction commits, and that the websocket is connected. |
| Worked before the 20.0 migration, not now | The channel changed. A subscriber joined to the old string channel `observability/<model_name>` receives nothing; see the migration section. |
| Serialization errors | Ensure all values in `notification_data` are JSON-serializable (e.g. use `float()` for `Decimal`, ISO strings for dates). |
| Notifications for unsaved records | Notifications are skipped for records without an ID; call `real_time_notify()` after the record is committed (e.g. after `create`/`write` in a committed transaction). |

---

## 8. Migration to Odoo 20.0

### 8.1 The channel is no longer a guessable string

Messages used to go to the string channel `observability/<model_name>`. Odoo
accepts **any string channel a client asks for**
(`ir.websocket._prepare_subscribe_data`), so anyone with a websocket could
listen to `observability/sale.order` and read everything the mixin published.
Odoo says as much in `bus.bus._sendone`: *"target (if str) should not be
guessable by an attacker"*.

The channel is now the **Real-Time Observer group record**. Odoo subscribes
users to their own groups' channels and to nothing else, so membership is the
whole access control. The model name moved to the notification type, which is
what the client subscribes to anyway.

**This is a breaking change on the wire.** A subscriber that joined the old
string channel receives nothing now; put its user in the observer group and
subscribe to the notification type instead.

### 8.2 A recordset used to send the same record N times

The notification was built inside a `for` loop and read back from a
`postcommit` closure, which captures the variable rather than its value. So
`records.real_time_notify(...)` over N records sent N copies of the **last**
one. Every record now gets its own message.

### 8.3 The extra cursor is gone

`bus.bus._sendone` already writes its row in the current transaction and
signals after the commit. The module wrapped that in another `postcommit`,
another cursor and another commit, which bought nothing and is where the
closure bug lived.

### 8.4 The documented JavaScript snippet now works

`bus.subscribe()` filters by notification **type**, not by channel, and the
module used to send the type `'notification'`. The snippet in this README
never matched anything. It does now.

### 8.5 Smaller things

- `real_time_notify()` returns how many notifications went out, instead of `None`.
- The message carries `model`, so one handler can serve several types.
- `_observability_payload()` is the seam for changing the message.
- `security/security.xml` held nothing but comments and is gone.
- `depends` no longer lists `base`.

## 9. Tests

The mixin can only be exercised on a model that inherits it, and a model can
only be registered by a module, so the suite lives in
`numa_real_time_observability_test` together with the probe model it needs.

```bash
odoo-bin -d <database> -i numa_real_time_observability_test --without-demo \
         --test-enable --test-tags=/numa_real_time_observability_test --stop-after-init
```

It covers the payload, one message per record, the condition, data that cannot
be serialized, empty and unsaved records, and the channel. Three of the tests
open a **real websocket**: one asserts that an observer receives the message,
one that an employee outside the group does not, and one that subscribing to
the old string channel gets nothing. They need `websocket-client`, which is in
this repository's `requirements.txt`.

---

## 10. Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | This file: overview, installation, API summary, and architecture summary. |
| [USER_GUIDE.md](USER_GUIDE.md) | Detailed usage examples (server and client), patterns, and integration scenarios. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Internal design, data flow, and implementation notes for developers. |

---

## 11. License and Author

- **Copyright:** NUMA Extreme Systems  
- **License:** LGPL-3  
- **Website:** [http://www.numaes.com](http://www.numaes.com)
