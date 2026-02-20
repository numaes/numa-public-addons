# User Guide: NUMA Real-Time Observability

This guide provides usage examples and recommended practices for the Real-Time Observability mixin in server-side (Python) and frontend (JavaScript) contexts. For an overview, installation, and API summary, see [README.md](README.md). For implementation details, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Table of Contents

1. [Server-Side Usage](#server-side-usage)
2. [Frontend Usage](#frontend-usage)
3. [Common Patterns](#common-patterns)
4. [Advanced Scenarios](#advanced-scenarios)
5. [Integration Examples](#integration-examples)

## Server-Side Usage

### Basic Example

Apply the mixin to your model and call `real_time_notify()` after the relevant business logic:

```python
from odoo import models, fields, api

class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'real.time.observability.mixin']
    
    state = fields.Selection([
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
    ])
    
    def action_start(self):
        """Start working on the task."""
        self.write({'state': 'in_progress'})
        self.real_time_notify({
            'event': 'task_started',
            'task_id': self.id,
            'user_id': self.env.user.id,
            'timestamp': fields.Datetime.now().isoformat(),
        })
        return True
```

### Example: State Change Notifications

Publish notifications when a record’s state changes:

```python
class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'real.time.observability.mixin']
    
    def action_confirm(self):
        """Confirm the sale order."""
        result = super().action_confirm()
        
        # Send notification with order details
        self.real_time_notify({
            'event': 'order_confirmed',
            'order_id': self.id,
            'partner_id': self.partner_id.id,
            'amount_total': float(self.amount_total),
            'state': self.state,
        })
        
        return result
    
    def action_cancel(self):
        """Cancel the sale order."""
        result = super().action_cancel()
        
        self.real_time_notify({
            'event': 'order_cancelled',
            'order_id': self.id,
            'reason': self.env.context.get('cancel_reason', 'Unknown'),
        })
        
        return result
```

### Example: Conditional Notifications

Use the `condition` parameter to send notifications only when specified conditions are met:

```python
class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'real.time.observability.mixin']
    
    def button_validate(self):
        """Validate the picking."""
        result = super().button_validate()
        
        # Only notify for high-value shipments
        self.real_time_notify(
            notification_data={
                'event': 'picking_validated',
                'picking_id': self.id,
                'total_value': float(sum(self.move_ids.mapped('value'))),
            },
            condition=lambda record: sum(record.move_ids.mapped('value')) > 10000
        )
        
        return result
```

### Example: Batch Operations

Publish notifications for batch operations; the mixin supports recordsets (one notification per record, or a single summary event from one record):

```python
class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'real.time.observability.mixin']
    
    def action_post(self):
        """Post the invoice."""
        result = super().action_post()
        
        # Notify about posting
        self.real_time_notify({
            'event': 'invoice_posted',
            'invoice_id': self.id,
            'invoice_type': self.move_type,
            'amount_total': float(self.amount_total),
            'partner_id': self.partner_id.id,
        })
        
        return result
    
    @api.model
    def batch_post(self, move_ids):
        """Post multiple invoices."""
        moves = self.browse(move_ids)
        moves.action_post()
        
        # Each move will send its own notification
        # You can also send a summary notification
        moves[0].real_time_notify({
            'event': 'batch_posted',
            'count': len(moves),
            'move_ids': move_ids,
        })
        
        return True
```

### Example: Consuming Notifications (Python)

The addon only sends notifications; consumption on the backend depends on your bus listener. The following illustrates how to process messages once they are received:

```python
from odoo import models
import json

class NotificationListener(models.Model):
    _name = 'notification.listener'
    
    def process_notification(self, channel, message):
        """
        Process a notification received from the bus.
        Typically invoked by an external bus listener service.
        """
        if channel.startswith('observability/'):
            model_name = channel.replace('observability/', '')
            record_id = message.get('id')
            notification_data = message.get('notification_data', {})
            
            event = notification_data.get('event')
            
            if event == 'order_confirmed':
                self._handle_order_confirmed(model_name, record_id, notification_data)
            elif event == 'task_started':
                self._handle_task_started(model_name, record_id, notification_data)
    
    def _handle_order_confirmed(self, model_name, record_id, data):
        """Handle order confirmed event."""
        # Your business logic here
        self.env['sale.order'].browse(record_id).message_post(
            body=f"Order confirmed notification received: {data}"
        )
    
    def _handle_task_started(self, model_name, record_id, data):
        """Handle task started event."""
        # Your business logic here
        pass
```

## Frontend Usage

### Basic Example: Subscribing to Notifications

In an Odoo JavaScript module, subscribe to the model’s channel and handle incoming messages:

```javascript
import { bus } from "@web/core/bus/bus";
import { Component, onMounted, onWillUnmount } from "@odoo/owl";

export class NotificationListener extends Component {
    setup() {
        this.channel = "observability/sale.order";
        
        onMounted(() => {
            // Subscribe to notifications
            bus.subscribe(this.channel, this.onNotification.bind(this));
        });
        
        onWillUnmount(() => {
            // Unsubscribe when component is destroyed
            bus.unsubscribe(this.channel, this.onNotification.bind(this));
        });
    }
    
    onNotification(notification) {
        const { id, notification_data } = notification;
        console.log("Received notification:", notification);
        
        if (notification_data.event === 'order_confirmed') {
            this.handleOrderConfirmed(id, notification_data);
        }
    }
    
    handleOrderConfirmed(orderId, data) {
        // Update UI, show notification, refresh data, etc.
        this.env.services.notification.add(
            `Order ${orderId} has been confirmed!`,
            { type: "success" }
        );
        
        // Optionally reload related views
        this.env.services.orm.silent.reload();
    }
}
```

### Example: Using the Bus Service

When using Odoo’s bus service for channel management:

```javascript
import { busService } from "@web/core/bus_service";

export class MyComponent extends Component {
    setup() {
        this.busService = this.env.services.bus_service;
        this.channel = "observability/project.task";
        
        onMounted(() => {
            // Add channel and subscribe
            this.busService.addChannel(this.channel);
            this.busService.subscribe("notification", this.onNotification.bind(this));
        });
        
        onWillUnmount(() => {
            // Clean up
            this.busService.unsubscribe(this.channel, "notification", this.onNotification);
        });
    }
    
    onNotification(notification) {
        if (notification.channel === this.channel) {
            const { id, notification_data } = notification.payload;
            
            if (notification_data.event === 'task_started') {
                this.showTaskNotification(id, notification_data);
            }
        }
    }
    
    showTaskNotification(taskId, data) {
        // Show a notification to the user
        this.env.services.notification.add(
            `Task ${taskId} has been started by ${data.user_id}`,
            { type: "info", sticky: true }
        );
    }
}
```

### Example: Real-Time Dashboard Updates

Keep a dashboard in sync with backend events by subscribing to the relevant channel and updating local state:

```javascript
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { bus } from "@web/core/bus/bus";

export class SalesDashboard extends Component {
    setup() {
        this.state = useState({
            orders: [],
            totalRevenue: 0,
        });
        
        onMounted(() => {
            this.loadInitialData();
            this.setupNotifications();
        });
        
        onWillUnmount(() => {
            bus.unsubscribe("observability/sale.order", this.onOrderNotification);
        });
    }
    
    async loadInitialData() {
        // Load initial dashboard data
        const orders = await this.env.services.orm.searchRead(
            "sale.order",
            [["state", "=", "sale"]],
            ["id", "name", "amount_total", "date_order"]
        );
        
        this.state.orders = orders;
        this.state.totalRevenue = orders.reduce(
            (sum, order) => sum + order.amount_total, 
            0
        );
    }
    
    setupNotifications() {
        bus.subscribe("observability/sale.order", this.onOrderNotification.bind(this));
    }
    
    onOrderNotification(notification) {
        const { id, notification_data } = notification;
        
        if (notification_data.event === 'order_confirmed') {
            // Add new order to dashboard
            this.state.orders.push({
                id: id,
                name: notification_data.order_name,
                amount_total: notification_data.amount_total,
                date_order: notification_data.date_order,
            });
            
            // Update total revenue
            this.state.totalRevenue += notification_data.amount_total;
            
            // Show notification
            this.env.services.notification.add(
                `New order confirmed: ${notification_data.order_name}`,
                { type: "success" }
            );
        }
    }
}
```

### Example: Real-Time Form Updates

Refresh a form or detail view when related records change by subscribing to the model channel and filtering by record ID:

```javascript
import { Component, onMounted, onWillUnmount } from "@odoo/owl";
import { bus } from "@web/core/bus/bus";

export class TaskForm extends Component {
    setup() {
        this.taskId = this.props.taskId;
        
        onMounted(() => {
            // Listen for updates to this specific task
            bus.subscribe("observability/project.task", this.onTaskUpdate.bind(this));
        });
        
        onWillUnmount(() => {
            bus.unsubscribe("observability/project.task", this.onTaskUpdate);
        });
    }
    
    onTaskUpdate(notification) {
        const { id, notification_data } = notification;
        
        // Only process notifications for this task
        if (id !== this.taskId) {
            return;
        }
        
        if (notification_data.event === 'task_started') {
            // Update the form to show the task is in progress
            this.env.services.orm.silent.reload();
            
            this.env.services.notification.add(
                "Task has been started",
                { type: "info" }
            );
        } else if (notification_data.event === 'task_completed') {
            // Update the form to show the task is done
            this.env.services.orm.silent.reload();
            
            this.env.services.notification.add(
                "Task has been completed!",
                { type: "success" }
            );
        }
    }
}
```

## Common Patterns

### Pattern 1: State Machine Notifications

Publish a notification on every state transition:

```python
class WorkflowModel(models.Model):
    _name = 'workflow.model'
    _inherit = ['workflow.model', 'real.time.observability.mixin']
    
    state = fields.Selection([...])
    
    def _notify_state_change(self, old_state, new_state):
        """Helper method to notify state changes."""
        self.real_time_notify({
            'event': 'state_changed',
            'old_state': old_state,
            'new_state': new_state,
            'timestamp': fields.Datetime.now().isoformat(),
        })
    
    def action_next_state(self):
        old_state = self.state
        # Your state transition logic
        self.write({'state': 'next_state'})
        self._notify_state_change(old_state, self.state)
```

### Pattern 2: User Activity Tracking

Publish events when users perform actions (e.g. open, edit):

```python
class Document(models.Model):
    _name = 'document'
    _inherit = ['document', 'real.time.observability.mixin']
    
    def action_open(self):
        self.real_time_notify({
            'event': 'document_opened',
            'user_id': self.env.user.id,
            'user_name': self.env.user.name,
            'timestamp': fields.Datetime.now().isoformat(),
        })
    
    def action_edit(self):
        self.real_time_notify({
            'event': 'document_edited',
            'user_id': self.env.user.id,
        })
```

### Pattern 3: Threshold-Based Notifications

Publish notifications when business thresholds are crossed (e.g. low stock):

```python
class Inventory(models.Model):
    _name = 'stock.quant'
    _inherit = ['stock.quant', 'real.time.observability.mixin']
    
    def _check_thresholds(self):
        """Check if stock levels cross thresholds."""
        if self.quantity < self.product_id.reordering_min_qty:
            self.real_time_notify({
                'event': 'low_stock',
                'product_id': self.product_id.id,
                'current_qty': self.quantity,
                'min_qty': self.product_id.reordering_min_qty,
            })
```

## Advanced Scenarios

### Scenario 1: Multi-Model Notifications

Send notifications from related models:

```python
class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'real.time.observability.mixin']
    
    def action_confirm(self):
        result = super().action_confirm()
        
        # Notify about the order
        self.real_time_notify({
            'event': 'order_confirmed',
            'order_id': self.id,
        })
        
        # Also notify about related invoice creation
        for invoice in self.invoice_ids:
            invoice.real_time_notify({
                'event': 'invoice_created_from_order',
                'order_id': self.id,
                'invoice_id': invoice.id,
            })
        
        return result
```

### Scenario 2: Conditional Notifications with Complex Logic

Use a callable that combines several conditions:

```python
class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'real.time.observability.mixin']
    
    def action_done(self):
        result = super().action_done()
        
        # Only notify if task is in a critical project
        self.real_time_notify(
            notification_data={
                'event': 'task_completed',
                'task_id': self.id,
                'project_id': self.project_id.id,
            },
            condition=lambda record: (
                record.project_id.priority == 'high' and
                record.user_id.id == self.env.user.id
            )
        )
        
        return result
```

### Scenario 3: Frontend Multi-Channel Subscription

Subscribe to several model channels and route messages to the appropriate handler:

```javascript
export class MultiChannelListener extends Component {
    setup() {
        this.channels = [
            "observability/sale.order",
            "observability/project.task",
            "observability/account.move",
        ];
        
        onMounted(() => {
            this.channels.forEach(channel => {
                bus.subscribe(channel, this.onNotification.bind(this));
            });
        });
        
        onWillUnmount(() => {
            this.channels.forEach(channel => {
                bus.unsubscribe(channel, this.onNotification);
            });
        });
    }
    
    onNotification(notification) {
        const channel = notification.channel || "unknown";
        const modelName = channel.replace("observability/", "");
        
        // Route to appropriate handler
        switch(modelName) {
            case "sale.order":
                this.handleSaleOrder(notification);
                break;
            case "project.task":
                this.handleProjectTask(notification);
                break;
            case "account.move":
                this.handleAccountMove(notification);
                break;
        }
    }
    
    handleSaleOrder(notification) {
        // Handle sale order notifications
    }
    
    handleProjectTask(notification) {
        // Handle project task notifications
    }
    
    handleAccountMove(notification) {
        // Handle account move notifications
    }
}
```

## Integration Examples

### Integration with Background Jobs

Combine the mixin with background job systems by sending notifications when a job starts, progresses, or completes:

```python
class LongRunningProcess(models.Model):
    _name = 'long.running.process'
    _inherit = ['long.running.process', 'real.time.observability.mixin']
    
    def execute(self):
        # Start background job
        job = self.env['res.background_job'].create({
            'name': f'Process {self.name}',
            'model': self._name,
            'res_id': self.id,
            'method': 'do_process',
        })
        
        # Notify that process started
        self.real_time_notify({
            'event': 'process_started',
            'job_id': job.id,
        })
        
        return job
    
    def do_process(self, job):
        # Long running process
        for i in range(100):
            # Do work
            job.update_status(rate=i, statusMsg=f'Processing {i}%')
            
            # Notify progress
            self.real_time_notify({
                'event': 'process_progress',
                'progress': i,
            })
        
        # Notify completion
        self.real_time_notify({
            'event': 'process_completed',
            'result': 'success',
        })
```

### Integration with FSM (Finite State Machine)

Publish notifications when finite state machine transitions occur:

```python
class FSMInstance(models.Model):
    _name = 'fsm.instance'
    _inherit = ['fsm.instance', 'real.time.observability.mixin']
    
    def trigger_event(self, event_name):
        """Trigger an FSM event and notify."""
        result = super().trigger_event(event_name)
        
        self.real_time_notify({
            'event': 'fsm_event_triggered',
            'event_name': event_name,
            'current_state': self.state,
            'previous_state': self._previous_state,
        })
        
        return result
```

## Best Practices Summary

1. **Include record ID in payloads** so that listeners can load full record data when needed.
2. **Use consistent event names** (e.g. `model_action`) and document them.
3. **Keep payloads small**; include only essential data and let listeners fetch more if required.
4. **Handle errors in listeners**; the mixin isolates send failures, but subscribers should handle missing or malformed messages.
5. **Test with real commits**; notifications are sent only after a successful commit.
6. **Document events and payloads** for each model that uses the mixin.
7. **Use the `condition` parameter** to avoid sending notifications that no subscriber needs; keep conditions simple and readable.

## Troubleshooting

### Notifications Not Appearing

1. Confirm that the model inherits from `real.time.observability.mixin`.
2. Ensure the code path that calls `real_time_notify()` runs and that the transaction commits.
3. Check Odoo server logs for validation or send errors.
4. Verify the subscription channel is `observability/<model_name>`.

### Frontend Not Receiving Notifications

1. Ensure the bus service is initialized and the channel is added if required.
2. Confirm the component subscribes to the correct channel before events are sent.
3. Check the browser console for JavaScript errors.
4. Ensure the subscription is active while the component is mounted.

### Performance

1. Reduce notification frequency or use the `condition` parameter to filter events.
2. Keep `notification_data` small; avoid large nested structures.
3. For bulk operations, consider sending a single summary notification instead of one per record where appropriate.
