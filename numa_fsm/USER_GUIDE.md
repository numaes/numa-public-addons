# Numa FSM User Guide

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Architecture & Current Status](#architecture--current-status)
4. [Integration with numa_poly](#integration-with-numa_poly)
5. [Getting Started](#getting-started)
6. [Advanced Features](#advanced-features)
7. [Examples](#examples)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

---

## Overview

**Numa FSM** is a powerful Finite State Machine (FSM) engine for Odoo that provides visual workflow design combined with robust asynchronous execution. Built on `numa_poly` for polymorphic inheritance support, it enables any Odoo model to become a state machine, making it ideal for complex business processes, workflow automation, and state-driven applications.

### What Makes Numa FSM Special?

- **Visual Designer**: Drag-and-drop interface to design workflows graphically
- **Asynchronous Processing**: Events are processed asynchronously using `numa_asynch_exec`, ensuring non-blocking operations
- **Persistent Execution**: All events are persisted in the database, allowing for retry and recovery
- **Polymorphic by Design**: Built on `numa_poly`, enabling any model to inherit FSM capabilities
- **Global Events**: Support for events that can be handled in any state
- **Precise Timers**: Timer-based events execute every second with continuous retry capability

---

## Key Features

### 1. Visual Workflow Design

Design complex workflows using an intuitive drag-and-drop interface:
- **States**: Represent stable conditions where the FSM waits for events
- **Transitions**: Execute Python code and determine outcomes
- **Events**: Trigger transitions from states
- **Outcomes**: Map transition results to destination states

### 2. Asynchronous Event Processing

All events are processed asynchronously through `numa_asynch_exec`:
- Events are persisted in `numa.asynch.job` before execution
- Automatic retries on failure
- No blocking of calling threads or HTTP requests
- Full visibility into job status and execution history

### 3. Timer Management

Timer-based events execute with high precision:
- **Execution Frequency**: Every 1 second (configurable via `retry_delay`)
- **Continuous Operation**: Uses `retry_count = -1` for infinite retries
- **Self-Scheduling**: Automatically schedules next execution
- **No Cron Dependency**: Runs independently of Odoo's cron system

### 4. Global Events

Support for events available in any state:
- **Priority System**: Current state events have priority over global events
- **Common Handlers**: Define once (e.g., `timeout`, `cancel`) and use everywhere
- **Clean Design**: Reduces duplication and improves maintainability

### 5. Polymorphic Integration

Built on `numa_poly` for flexible inheritance:
- Any Odoo model can become a state machine
- Multiple inheritance support
- Clean separation of concerns

---

## Architecture & Current Status

### Current Implementation Status

✅ **Fully Implemented:**
- Integration with `numa_asynch_exec` for asynchronous event processing
- Timer system with continuous execution (every 1 second)
- Global event support with priority handling
- Visual workflow designer (OWL-based)
- Transactional execution engine

⏳ **Pending (Frontend):**
- Visual editor support for marking states as "global"
- UI differentiation for global states in the diagram
- Validation UI for global state constraints

### Core Components

#### 1. `fsm.definition` - The Blueprint

Stores the FSM design:
- **`json_ui_schema`**: Visual layout and topology (managed by OWL editor)
- **`json_compiled_definition`**: Executable representation (auto-generated)
- **`state`**: Definition lifecycle (`draft`, `test`, `production`)

#### 2. `fsm.instance` - The Execution

Represents a running FSM instance:
- **`state`**: Execution state (`init`, `running`, `paused`, `ended`, `error`)
- **`current_state_id`**: Current state node ID
- **`instance_variables`**: Persistent variables across states
- **`intermediate_variables`**: Temporary variables during transitions

#### 3. `fsm.timer` - Timer Management

Manages scheduled events:
- **`trigger_at`**: When the timer should fire
- **`json_event`**: Event data to send
- **`fsm_instance_id`**: Target FSM instance

### Execution Flow

1. **Event Received**: `process_event()` queues event for asynchronous processing
2. **Job Created**: Event persisted in `numa.asynch.job`
3. **Async Execution**: `_process_event_sync()` processes the event
4. **Handler Lookup**: Searches for event handler (current state → global state)
5. **Transition Execution**: Executes Python code, determines outcome
6. **State Update**: Updates instance state atomically
7. **Chain Execution**: Continues until reaching a state or end node

---

## Integration with numa_poly

### Understanding Polymorphic Inheritance

`numa_poly` enables multiple inheritance in Odoo, allowing models to inherit from multiple base models simultaneously. `numa_fsm` is built on this foundation, enabling any Odoo model to become a state machine.

### Basic Integration Pattern

```python
from collections import OrderedDict
from odoo import models, fields, api

class MyBusinessModel(models.Model):
    _name = 'my.business.model'
    _description = 'My Business Model'
    
    # Define polymorphic dependencies
    _depend_models = OrderedDict({
        'fsm.instance': 'fsm_instance_id'  # Map fsm.instance to a field
    })
    
    name = fields.Char('Name')
    fsm_instance_id = fields.Many2one('fsm.instance', 'FSM Instance')
    
    # Your business logic here
    def process_data(self):
        # Access FSM instance through polymorphic relationship
        fsm_instance = self.as_fsm_instance()
        if fsm_instance:
            fsm_instance.send_event({'name': 'data_processed'})
```

### Direct Inheritance Pattern

For simpler cases, you can inherit directly from `fsm.instance`:

```python
from collections import OrderedDict
from odoo import models, fields, api

class OrderWorkflow(models.Model):
    _name = 'order.workflow'
    _description = 'Order Workflow'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    # Empty dependencies means no polymorphic relationship
    # The model itself is an FSM instance
    _depend_models = OrderedDict()
    
    # Standard fields
    order_number = fields.Char('Order Number')
    customer_id = fields.Many2one('res.partner', 'Customer')
    
    # FSM instance fields are inherited implicitly
    # You can access: state, current_state_id, instance_variables, etc.
    
    def approve_order(self):
        """Business method that triggers FSM event"""
        self.send_event({'name': 'approve'})
```

### Practical Example: Order Management System

Let's create a complete example showing how to integrate FSM with a business model:

```python
from collections import OrderedDict
from odoo import models, fields, api, exceptions

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'mail.thread', 'mail.activity.mixin']
    
    # Polymorphic relationship to FSM instance
    _depend_models = OrderedDict({
        'fsm.instance': 'order_fsm_id'
    })
    
    order_fsm_id = fields.Many2one('fsm.instance', 'Order Workflow', readonly=True)
    
    def action_confirm(self):
        """Override to integrate with FSM"""
        res = super().action_confirm()
        
        # Create FSM instance if not exists
        if not self.order_fsm_id:
            fsm_def = self.env['fsm.definition'].search([
                ('name', '=', 'Order Processing'),
                ('state', '=', 'production')
            ], limit=1)
            
            if fsm_def:
                fsm_instance = self.env['fsm.instance'].create({
                    'definition_id': fsm_def.id,
                    'name': f'ORDER-{self.name}',
                })
                self.order_fsm_id = fsm_instance
                fsm_instance.start()
        
        # Send event to FSM
        if self.order_fsm_id:
            self.order_fsm_id.send_event({'name': 'order_confirmed'})
        
        return res
    
    def action_cancel(self):
        """Cancel order and notify FSM"""
        res = super().action_cancel()
        if self.order_fsm_id:
            self.order_fsm_id.send_event({'name': 'cancel'})
        return res
    
    def action_process_payment(self):
        """Process payment and notify FSM"""
        # Your payment processing logic here
        payment_success = self._process_payment()
        
        if payment_success and self.order_fsm_id:
            self.order_fsm_id.send_event({
                'name': 'payment_processed',
                'amount': self.amount_total,
                'payment_method': self.payment_method
            })
```

### Accessing FSM Instance in Transition Code

In your FSM transition Python code, the FSM instance is available as `model`:

```python
# In a transition code snippet
# Access the FSM instance
fsm_instance = model  # model is the fsm.instance

# Access related business model through polymorphic relationship
if hasattr(fsm_instance, 'as_sale_order'):
    sale_order = fsm_instance.as_sale_order()
    if sale_order:
        # Work with the sale order
        sale_order.write({'state': 'processing'})
        log(f"Processing order: {sale_order.name}")

# Set outcome
outcome = 'success'
```

### Example: Complete Order Processing Workflow

Here's a complete example demonstrating a realistic order processing workflow:

```python
# 1. FSM Definition (created via UI, but shown as conceptual structure)

# State: "Pending Payment"
#   Event: "payment_received"
#   → Transition: "Process Payment"
#   → Outcomes: "success" → "Processing", "failed" → "Payment Failed"

# State: "Processing"
#   Event: "inventory_reserved"
#   → Transition: "Reserve Inventory"
#   → Outcomes: "success" → "Shipped", "failed" → "Inventory Error"

# State: "Shipped"
#   Event: "delivery_confirmed"
#   → Transition: "Complete Order"
#   → Outcomes: "success" → "Completed"

# Global State (for events available in any state)
#   Event: "cancel"
#   → Transition: "Cancel Order"
#   → Outcomes: "success" → "Cancelled"

# 2. Sale Order Model with FSM Integration

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order']
    
    _depend_models = OrderedDict({
        'fsm.instance': 'order_fsm_id'
    })
    
    order_fsm_id = fields.Many2one('fsm.instance', 'Order FSM')
    
    def action_confirm(self):
        """Start FSM workflow when order is confirmed"""
        res = super().action_confirm()
        
        fsm_def = self.env['fsm.definition'].search([
            ('name', '=', 'Order Processing'),
            ('state', '=', 'production')
        ], limit=1)
        
        if fsm_def and not self.order_fsm_id:
            self.order_fsm_id = self.env['fsm.instance'].create({
                'definition_id': fsm_def.id,
                'name': f'ORDER-{self.name}',
            })
            self.order_fsm_id.start()
        
        return res

# 3. Payment Processing Controller

from odoo import http
from odoo.http import request

class PaymentController(http.Controller):
    @http.route('/payment/notification', type='json', auth='public')
    def payment_notification(self, order_id, status, **kwargs):
        """Webhook from payment gateway"""
        order = request.env['sale.order'].browse(order_id)
        
        if status == 'paid' and order.order_fsm_id:
            order.order_fsm_id.send_event({
                'name': 'payment_received',
                'payment_id': kwargs.get('payment_id'),
                'amount': kwargs.get('amount')
            })
        
        return {'status': 'ok'}

# 4. Transition Code Example (from "Process Payment" transition)

# Access FSM instance
fsm_instance = model  # model is the fsm.instance

# Get related order through polymorphic relationship
sale_order = None
if hasattr(fsm_instance, 'as_sale_order'):
    sale_order = fsm_instance.as_sale_order()

if not sale_order:
    outcome = 'failed'
    log("No related sale order found")
else:
    # Access event data
    event = variables.get('event', {})
    payment_id = event.get('payment_id')
    
    # Business logic
    try:
        # Update order with payment info
        sale_order.write({
            'payment_status': 'paid',
            'payment_id': payment_id
        })
        
        # Log the event
        log(f"Payment processed for order {sale_order.name}")
        
        outcome = 'success'
    except Exception as e:
        log(f"Payment processing failed: {e}")
        outcome = 'failed'
```

---

## Getting Started

### Step 1: Install Dependencies

Ensure the following modules are installed:
- `numa_poly` - Polymorphic inheritance support
- `numa_asynch_exec` - Asynchronous execution infrastructure
- `mail` - Messaging and chatter support

### Step 2: Create an FSM Definition

1. Navigate to **FSM > Definitions**
2. Click **Create**
3. Enter a name (e.g., "Order Processing")
4. Switch to the **Designer** tab
5. Design your workflow:
   - Double-click canvas to add nodes (States, Transitions, End)
   - Double-click nodes to edit properties
   - Connect nodes by dragging from output ports to input ports

### Step 3: Define States and Transitions

**States:**
- Represent stable conditions
- Have associated events
- Wait for events to trigger transitions

**Transitions:**
- Execute Python code
- Set an `outcome` variable
- Map outcomes to destination states

**Example Transition Code:**
```python
# Access variables and FSM instance
variables = variables  # Dict of instance variables
model = model  # The fsm.instance object
env = env  # Odoo environment
log = log  # Logging function

# Access event data (if available)
event = variables.get('event', {})

# Your business logic
if some_condition:
    outcome = 'success'
else:
    outcome = 'failed'
```

### Step 4: Integrate with Your Model

**Option A: Polymorphic Relationship (Recommended for existing models)**

```python
class MyModel(models.Model):
    _name = 'my.model'
    _inherit = ['my.model']  # Your base model
    
    _depend_models = OrderedDict({
        'fsm.instance': 'fsm_instance_id'
    })
    
    fsm_instance_id = fields.Many2one('fsm.instance', 'FSM Instance')
    
    def start_workflow(self):
        fsm_def = self.env['fsm.definition'].search([
            ('name', '=', 'My Workflow'),
            ('state', '=', 'production')
        ], limit=1)
        
        if fsm_def:
            self.fsm_instance_id = self.env['fsm.instance'].create({
                'definition_id': fsm_def.id,
            })
            self.fsm_instance_id.start()
```

**Option B: Direct Inheritance (For new models)**

```python
class MyWorkflowModel(models.Model):
    _name = 'my.workflow.model'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    _depend_models = OrderedDict()  # Empty = model IS the FSM instance
    
    # Your business fields
    # FSM fields (state, current_state_id, etc.) are inherited
```

### Step 5: Send Events

```python
# Send event to FSM instance
instance.send_event({
    'name': 'event_name',
    'data': 'your_data'
})

# Events are processed asynchronously via numa_asynch_exec
# Check numa.asynch.job for execution status
```

### Step 6: Monitor Execution

- Open the FSM instance form view
- View the visual diagram with current state highlighted
- Inspect `instance_variables` and `intermediate_variables`
- Check `numa.asynch.job` for event processing status
- Use chatter messages for execution logs

---

## Advanced Features

### Global Events

Global events are available in any state. They're useful for common handlers like `timeout`, `cancel`, or `abort`.

**How to Use:**

1. **Mark a state as global** in the UI schema (requires frontend support) or set `is_global: true` in JSON:

```json
{
  "nodes": [
    {
      "id": "global_state_1",
      "type": "state",
      "label": "Global Events",
      "is_global": true,
      "events": [
        {"name": "timeout", "target_transition_id": "timeout_transition"},
        {"name": "cancel", "target_transition_id": "cancel_transition"}
      ]
    }
  ]
}
```

2. **Priority handling**: If an event exists in both current state and global state, the current state handler takes priority.

### Timers

Schedule events to fire at specific times:

```python
# In transition code
# Start a timer that fires in 5 minutes
model.start_timer({
    'name': 'timeout',
    'action': 'expire'
}, delay=300)  # 300 seconds = 5 minutes

# Start a timer for a specific datetime
from odoo import fields
target_time = fields.Datetime.now() + timedelta(hours=1)
model.start_timer({
    'name': 'reminder',
    'message': 'Reminder notification'
}, at=target_time)

# Stop a specific timer
model.stop_timer('timeout')

# Stop all timers
model.stop_all_timers()
```

### Variable Management

FSM instances maintain two types of variables:

**Instance Variables** (`instance_variables`):
- Persistent across states
- Updated atomically when chain completes
- Accessible in all transitions

**Intermediate Variables** (`intermediate_variables`):
- Temporary during transition chains
- Reset after chain completion
- Used for transactional execution

```python
# In transition code
# Access instance variables
order_id = variables.get('order_id')
customer_name = variables.get('customer_name')

# Modify variables (will be persisted after chain completes)
variables['order_id'] = 123
variables['processed_count'] = variables.get('processed_count', 0) + 1

# Access event data
event = variables.get('event', {})
event_name = event.get('name')
event_data = event.get('data')
```

### Debugging

**Step-by-Step Execution:**
- Set `debug_mode` to `'step_by_step'` on FSM instance
- Execution will pause at each transition
- Use "Next Step" button to proceed

**Breakpoints:**
- Mark transitions as breakpoints in the definition
- Execution pauses automatically at breakpoints

**Logging:**
```python
# In transition code
log("Processing order...")
log(f"Order ID: {variables.get('order_id')}")

# Logs appear in instance chatter
```

---

## Examples

### Example 1: Document Approval Workflow

```python
# FSM Definition Structure:
# - State: "Draft" → Event: "submit" → Transition: "Validate" → State: "Pending Review"
# - State: "Pending Review" → Event: "approve" → Transition: "Approve" → State: "Approved"
# - State: "Pending Review" → Event: "reject" → Transition: "Reject" → State: "Rejected"
# - Global State → Event: "cancel" → Transition: "Cancel" → State: "Cancelled"

# Document Model
class Document(models.Model):
    _name = 'document'
    
    _depend_models = OrderedDict({
        'fsm.instance': 'fsm_instance_id'
    })
    
    name = fields.Char('Document Name')
    fsm_instance_id = fields.Many2one('fsm.instance', 'Workflow')
    state = fields.Char('State', compute='_compute_state')
    
    def _compute_state(self):
        for rec in self:
            if rec.fsm_instance_id and rec.fsm_instance_id.current_state_id:
                # Get state label from definition
                compiled = json.loads(rec.fsm_instance_id.definition_id.json_compiled_definition)
                nodes = compiled.get('nodes', {})
                current = nodes.get(rec.fsm_instance_id.current_state_id, {})
                rec.state = current.get('label', 'Unknown')
            else:
                rec.state = 'Draft'
    
    def action_submit(self):
        if not self.fsm_instance_id:
            self._start_workflow()
        self.fsm_instance_id.send_event({'name': 'submit'})
    
    def action_approve(self):
        self.fsm_instance_id.send_event({'name': 'approve'})
    
    def action_reject(self):
        self.fsm_instance_id.send_event({
            'name': 'reject',
            'reason': self.env.context.get('rejection_reason')
        })
    
    def _start_workflow(self):
        fsm_def = self.env['fsm.definition'].search([
            ('name', '=', 'Document Approval'),
            ('state', '=', 'production')
        ], limit=1)
        
        self.fsm_instance_id = self.env['fsm.instance'].create({
            'definition_id': fsm_def.id,
            'instance_variables': {'document_id': self.id}
        })
        self.fsm_instance_id.start()
```

### Example 2: Onboarding Workflow with Steps

```python
# Onboarding Model
class Onboarding(models.Model):
    _name = 'onboarding'
    
    _depend_models = OrderedDict({
        'fsm.instance': 'fsm_instance_id'
    })
    
    name = fields.Char('Onboarding Name')
    partner_id = fields.Many2one('res.partner', 'Partner')
    fsm_instance_id = fields.Many2one('fsm.instance', 'Workflow')
    current_step = fields.Char('Current Step', compute='_compute_current_step')
    
    def _compute_current_step(self):
        for rec in self:
            if rec.fsm_instance_id:
                # Extract step from instance variables
                rec.current_step = rec.fsm_instance_id.instance_variables.get('current_step', 'Not Started')
    
    def start_onboarding(self):
        fsm_def = self.env['fsm.definition'].search([
            ('name', '=', 'User Onboarding'),
            ('state', '=', 'production')
        ], limit=1)
        
        self.fsm_instance_id = self.env['fsm.instance'].create({
            'definition_id': fsm_def.id,
            'instance_variables': {
                'onboarding_id': self.id,
                'partner_id': self.partner_id.id,
                'current_step': 'Initial Setup'
            }
        })
        self.fsm_instance_id.start()
    
    def complete_step(self, step_name):
        self.fsm_instance_id.send_event({
            'name': 'step_completed',
            'step': step_name
        })
```

### Example 3: Subscription Management

```python
# Subscription Model
class Subscription(models.Model):
    _name = 'subscription'
    
    _depend_models = OrderedDict({
        'fsm.instance': 'fsm_instance_id'
    })
    
    name = fields.Char('Subscription')
    partner_id = fields.Many2one('res.partner', 'Customer')
    state = fields.Selection([
        ('trial', 'Trial'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('expired', 'Expired')
    ])
    fsm_instance_id = fields.Many2one('fsm.instance', 'Subscription FSM')
    
    def start_trial(self):
        """Start subscription trial"""
        if not self.fsm_instance_id:
            self._init_fsm()
        self.fsm_instance_id.send_event({'name': 'start_trial'})
    
    def activate_subscription(self):
        """Activate subscription after trial"""
        self.fsm_instance_id.send_event({'name': 'activate'})
    
    def process_renewal(self):
        """Process subscription renewal"""
        self.fsm_instance_id.send_event({
            'name': 'renew',
            'renewal_period': 'monthly'
        })
    
    def _init_fsm(self):
        fsm_def = self.env['fsm.definition'].search([
            ('name', '=', 'Subscription Management'),
            ('state', '=', 'production')
        ], limit=1)
        
        self.fsm_instance_id = self.env['fsm.instance'].create({
            'definition_id': fsm_def.id,
            'instance_variables': {
                'subscription_id': self.id,
                'partner_id': self.partner_id.id
            }
        })
        self.fsm_instance_id.start()
```

---

## Best Practices

### 1. FSM Definition Design

- **Keep states focused**: Each state should represent a clear business condition
- **Minimize state count**: Too many states make workflows hard to understand
- **Use meaningful names**: State and event names should be self-explanatory
- **Document transitions**: Add comments in transition code explaining logic
- **Test thoroughly**: Use test instances before moving to production

### 2. Integration Patterns

- **Polymorphic relationships**: Use for existing models that need FSM capabilities
- **Direct inheritance**: Use for new models that are primarily state machines
- **One FSM per business object**: Don't create multiple FSMs for the same entity
- **Lifecycle management**: Create FSM instances when objects are created, clean up when deleted

### 3. Event Handling

- **Use global events** for common handlers (timeout, cancel, abort)
- **Keep event names consistent** across your application
- **Include relevant data** in event payloads
- **Handle missing handlers** gracefully (check logs)

### 4. Variable Management

- **Use instance_variables** for persistent data
- **Use intermediate_variables** only for temporary calculations
- **Document variable structure** in FSM definition
- **Avoid large data** in variables (store IDs, not full records)

### 5. Timer Usage

- **Clean up timers**: Always stop timers when no longer needed
- **Use specific event names**: Make timer events descriptive
- **Consider performance**: Too many active timers can impact system
- **Handle timer expiration**: Ensure handlers exist for timer events

### 6. Error Handling

- **Set outcomes properly**: Always set `outcome` in transition code
- **Log errors**: Use `log()` function for debugging
- **Handle exceptions**: Wrap risky operations in try-except
- **Rollback on errors**: Instance state is preserved on errors

### 7. Performance

- **Minimize transition code**: Keep Python code in transitions concise
- **Use async processing**: Events are already async, leverage it
- **Batch operations**: Process multiple instances when possible
- **Monitor job queue**: Watch `numa.asynch.job` for backlog

---

## Troubleshooting

### Events Not Processing

**Symptoms**: Events are sent but not processed.

**Solutions**:
1. Check `numa.asynch.job` model for pending/running jobs
2. Verify `numa_asynch_exec` module is installed and running
3. Check logs for error messages
4. Ensure FSM instance is in `running` state

### Timers Not Firing

**Symptoms**: Timers created but events never trigger.

**Solutions**:
1. Verify `_process_timers()` task is running (check `numa.asynch.job`)
2. Check timer `trigger_at` is in the past
3. Ensure `post_init_hook` ran during module installation
4. Check logs for timer processing errors

### Global Events Not Working

**Symptoms**: Global event handlers not found.

**Solutions**:
1. Verify state is marked as global (`is_global: true` in JSON)
2. Check `global_state_id` exists in compiled definition
3. Ensure event name matches exactly (case-sensitive)
4. Check that current state doesn't have a handler (priority system)

### Polymorphic Relationship Issues

**Symptoms**: Cannot access related model through polymorphic relationship.

**Solutions**:
1. Verify `_depend_models` is correctly defined
2. Ensure field name matches in `_depend_models` mapping
3. Check that related model exists and is accessible
4. Use `hasattr()` to check for polymorphic methods before calling

### Transition Code Errors

**Symptoms**: Transitions fail with Python errors.

**Solutions**:
1. Check transition code syntax
2. Verify all variables are defined before use
3. Use `log()` to debug variable values
4. Check instance chatter for error messages
5. Enable step-by-step debugging to isolate issues

---

## Additional Resources

- **Module Repository**: Check the module's source code for examples
- **numa_poly Documentation**: Understand polymorphic inheritance patterns
- **numa_asynch_exec Documentation**: Learn about asynchronous execution
- **Odoo Development Documentation**: Python and ORM best practices

---

**Version**: 18.0  
**Last Updated**: Current implementation status as of latest commits  
**Module**: numa_fsm  
**Dependencies**: numa_poly, numa_asynch_exec, mail, website
