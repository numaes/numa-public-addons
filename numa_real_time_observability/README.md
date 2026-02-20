# NUMA Real-Time Observability

**Odoo 18.0** | LGPL-3 | NUMA Extreme Systems

---

## 1. Overview

**NUMA Real-Time Observability** is an Odoo addon that provides a reusable mixin for publishing real-time events from any model via the Odoo bus. It enables server-side and client-side subscribers to react to model changes and business events without polling.

The addon introduces the abstract model `real.time.observability.mixin`. Any model that inherits from this mixin gains the method `real_time_notify()`, which schedules a bus notification to be sent **after a successful transaction commit**, ensuring that subscribers only receive events for persisted data.

### 1.1 Key Features

| Feature | Description |
|--------|-------------|
| **Mixin-based integration** | Apply to any Odoo model with a single inheritance line. |
| **Post-commit delivery** | Notifications are sent only after a successful database commit. |
| **Model-scoped channels** | Each model uses a dedicated bus channel: `observability/<model_name>`. |
| **Custom payloads** | Attach arbitrary, JSON-serializable data to each notification. |
| **Conditional notifications** | Optional callable to send notifications only when conditions are met. |
| **Error isolation** | Failures in notification delivery do not affect the main transaction. |
| **Dual consumption** | Events can be consumed from Python (backend) and JavaScript (frontend). |

### 1.2 Compatibility

- **Odoo version:** 18.0  
- **Dependencies:** `base`, `bus`  
- **License:** LGPL-3  

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

Subscribe to the model’s channel and handle incoming messages:

```javascript
import { bus } from "@web/core/bus/bus";

bus.subscribe("observability/sale.order", (message) => {
    const { id, notification_data } = message;
    if (notification_data.event === "order_confirmed") {
        // Update UI, refresh data, or show a notification
    }
});
```

### 3.3 Subscribing on the backend (Python)

Consumption on the backend depends on your bus listener implementation. Messages are sent to the channel `observability/<model_name>` with payload type `notification` and a body containing `id` and `notification_data`.

---

## 4. API Reference

### 4.1 Method: `real_time_notify(notification_data=False, condition=None)`

Schedules a bus notification to be sent after the current transaction is committed successfully. Supports recordsets; one notification per record is scheduled (subject to optional `condition`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `notification_data` | `dict` or `False` | No | Payload to attach to the notification. Must be JSON-serializable. Default: `{}`. |
| `condition` | `callable(record) -> bool` | No | If provided, the notification is sent only for records for which `condition(record)` is truthy. |

**Returns:** `None`

**Behaviour:**

- Records without an ID (e.g. new, unsaved) are skipped; a warning is logged.
- If `notification_data` is not a dict, it is wrapped as `{'data': notification_data}`; it must still be JSON-serializable.
- If serialization fails, an error is logged and no notification is scheduled.
- Notifications are sent via a post-commit hook; delivery errors are logged and do not affect the main transaction.

### 4.2 Channel and message format

- **Channel:** `observability/<model_name>` (e.g. `observability/sale.order`).
- **Message type:** `notification`.
- **Message body:**

```json
{
    "id": <integer record id>,
    "notification_data": { ... }
}
```

`notification_data` is the same dict passed to `real_time_notify()` (or its wrapped form).

---

## 5. Architecture Summary

1. **Call:** The model calls `real_time_notify(notification_data, condition)`.
2. **Validation:** The mixin ensures `notification_data` is JSON-serializable and prepares one message per record (respecting `condition`).
3. **Scheduling:** For each qualifying record, a post-commit hook is registered on the current cursor.
4. **Commit:** The main transaction commits.
5. **Delivery:** After commit, the hook runs in a new cursor, re-checks that the record exists, and calls `bus.bus._sendone(channel, 'notification', message)`.
6. **Consumption:** Subscribers (frontend or backend) receive the message on the corresponding `observability/<model_name>` channel.

For implementation details, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 6. Best Practices

- **Payload size:** Keep `notification_data` small; subscribers can load full records if needed.
- **Event naming:** Use clear, consistent event names (e.g. `order_confirmed`, `task_completed`).
- **Context:** Include IDs and minimal context (e.g. state, type) so listeners can act without extra queries when possible.
- **Conditions:** Use the `condition` parameter to avoid sending notifications that no subscriber needs.
- **Testing:** Verify behaviour in tests that perform real commits; notifications are only sent after commit.

---

## 7. Troubleshooting

| Issue | Checks |
|-------|--------|
| No notifications received | Confirm subscription to `observability/<model_name>`. Ensure the transaction commits and the bus service is running. Check Odoo logs for delivery errors. |
| Serialization errors | Ensure all values in `notification_data` are JSON-serializable (e.g. use `float()` for `Decimal`, ISO strings for dates). |
| Notifications for unsaved records | Notifications are skipped for records without an ID; call `real_time_notify()` after the record is committed (e.g. after `create`/`write` in a committed transaction). |

---

## 8. Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | This file: overview, installation, API summary, and architecture summary. |
| [USER_GUIDE.md](USER_GUIDE.md) | Detailed usage examples (server and client), patterns, and integration scenarios. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Internal design, data flow, and implementation notes for developers. |

---

## 9. License and Author

- **Copyright:** NUMA Extreme Systems  
- **License:** LGPL-3  
- **Website:** [http://www.numaes.com](http://www.numaes.com)
