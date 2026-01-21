# NUMA Real-Time Observability

A powerful Odoo module that provides real-time observability capabilities through a simple mixin pattern. This module enables any Odoo model to send real-time notifications via the Odoo bus system, allowing both server-side and frontend applications to react to model changes and events.

## Overview

The `numa_real_time_observability` module provides a mixin (`real.time.observability.mixin`) that can be applied to any Odoo model. When applied, the model gains access to a `real_time_notify()` method that sends notifications to the Odoo bus system with the topic `observability/<model_name>`.

### Key Features

- **Simple Integration**: Apply the mixin to any model with a single line
- **Post-Commit Safety**: Notifications are only sent after successful database commits
- **Flexible Data**: Send custom notification data with each event
- **Model-Specific Channels**: Automatic topic generation per model (`observability/<model_name>`)
- **Robust Error Handling**: Errors in notification sending don't break main transactions
- **Frontend & Backend Support**: Listen to notifications from both JavaScript and Python
- **Data Validation**: Automatic validation of JSON serializable data
- **Conditional Notifications**: Optional condition-based notification filtering

## Installation

1. Copy the `numa_real_time_observability` module to your Odoo addons directory
2. Update the app list in Odoo
3. Install the module through the Apps menu

### Dependencies

- `base` (Odoo core)
- `bus` (Odoo bus system for real-time notifications)

## Quick Start

### 1. Apply the Mixin to Your Model

```python
from odoo import models, fields

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'real.time.observability.mixin']
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('done', 'Done'),
    ])
    
    def action_confirm(self):
        result = super().action_confirm()
        # Send notification after successful commit
        self.real_time_notify({
            'event': 'order_confirmed',
            'state': self.state,
            'amount_total': self.amount_total,
        })
        return result
```

### 2. Listen to Notifications (Backend - Python)

```python
from odoo import models

class NotificationHandler(models.Model):
    _name = 'notification.handler'
    
    def setup_listener(self):
        # In a cron job or background process
        bus_model = self.env['bus.bus']
        # Listen to all observability channels
        # (Implementation depends on your bus listener setup)
        pass
```

### 3. Listen to Notifications (Frontend - JavaScript)

```javascript
// In your Odoo JavaScript module
import { bus } from "@web/core/bus/bus";

// Subscribe to notifications
bus.subscribe("observability/sale.order", (notification) => {
    console.log("Sale order notification:", notification);
    const { id, notification_data } = notification;
    // Handle the notification
    if (notification_data.event === 'order_confirmed') {
        // Update UI, show notification, etc.
    }
});
```

## Architecture

### Notification Flow

1. **Model Method Call**: Your model calls `real_time_notify(notification_data)`
2. **Data Validation**: The mixin validates that `notification_data` is JSON serializable
3. **Post-Commit Hook**: A post-commit hook is registered to send the notification
4. **Transaction Commit**: The main transaction commits successfully
5. **Notification Sent**: After commit, the notification is sent to the bus
6. **Bus Delivery**: The bus delivers the notification to all subscribers

### Channel Naming

Notifications are sent to channels following this pattern:
```
observability/<model_name>
```

For example:
- `observability/sale.order` for sale orders
- `observability/account.move` for invoices
- `observability/res.partner` for partners

### Message Format

Each notification message contains:

```json
{
    "id": 123,
    "notification_data": {
        "event": "order_confirmed",
        "state": "done",
        "amount_total": 1500.00
    }
}
```

## Advanced Usage

### Conditional Notifications

Send notifications only when certain conditions are met:

```python
def action_confirm(self):
    result = super().action_confirm()
    
    # Only notify if order amount is above threshold
    self.real_time_notify(
        notification_data={'event': 'order_confirmed'},
        condition=lambda record: record.amount_total > 1000
    )
    return result
```

### Batch Operations

The mixin works with recordsets:

```python
orders = self.env['sale.order'].browse([1, 2, 3])
orders.real_time_notify({
    'event': 'batch_processed',
    'count': len(orders)
})
```

Each record in the recordset will send its own notification with the same `notification_data`.

## Best Practices

1. **Keep notification_data small**: Large payloads can impact performance
2. **Use meaningful event names**: Make it easy to identify event types
3. **Include relevant context**: Add IDs, states, or other context that listeners might need
4. **Handle errors gracefully**: The mixin handles errors, but ensure your listeners do too
5. **Test with real commits**: Notifications only fire after successful commits

## Troubleshooting

### Notifications Not Received

1. **Check the channel name**: Ensure you're subscribing to `observability/<model_name>`
2. **Verify commit**: Notifications only send after successful commits
3. **Check logs**: Look for errors in the Odoo log file
4. **Verify bus service**: Ensure the bus service is running

### Data Serialization Errors

If you see serialization errors:
- Ensure all data in `notification_data` is JSON serializable
- Avoid complex objects, use primitives (strings, numbers, lists, dicts)
- Convert dates/datetimes to strings if needed

## License

This module is licensed under LGPL-3.

## Author

NUMA Extreme Systems - http://www.numaes.com

## Support

For detailed usage examples and advanced scenarios, see [USER_GUIDE.md](USER_GUIDE.md).
