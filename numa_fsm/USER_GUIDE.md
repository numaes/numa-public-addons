# Numa FSM — User and Developer Guide

This guide describes how to use and extend Numa FSM: design workflows in the visual editor, write transition code, integrate with business models, and operate timers and global events. All documentation is in professional English.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Key Concepts](#2-key-concepts)
3. [Core Components](#3-core-components)
4. [Transition Code Reference](#4-transition-code-reference)
5. [Integration with Business Models](#5-integration-with-business-models)
6. [Getting Started](#6-getting-started)
7. [Advanced Features](#7-advanced-features)
8. [Examples](#8-examples)
9. [Best Practices](#9-best-practices)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Overview

**Numa FSM** is a finite state machine engine for Odoo that combines a visual, graph-first designer with Python transition code. Workflows are defined as diagrams (states, transitions, start/end); decision logic is written in short Python snippets that run in a controlled environment. Events are processed asynchronously via `numa_asynch_exec`, and execution is transactional: instance variables are updated only when a transition chain reaches a state or end node.

### 1.1 What Numa FSM Provides

- **Visual designer:** Drag-and-drop canvas (OWL) to add states, transitions, and connections.
- **Outcome-based routing:** Transition code sets an outcome; the graph maps outcomes to target states.
- **Asynchronous event processing:** Events are queued and processed in the background (persistent, retriable).
- **Timers:** Schedule events to fire at a given time; processed every second.
- **Global state:** Optional state whose events are available in any current state.
- **Polymorphic integration:** Any model can hold an FSM instance (via `numa_poly` and a Many2one to `fsm.instance`).
- **Debugging:** Step-by-step execution, breakpoints, and chatter logs.

---

## 2. Key Concepts

### 2.1 Graph-First, Outcome-Based Execution

- **The graph** defines the topology: which states exist, which events lead to which transitions, and which outcomes lead to which states (or end).
- **Transition code** runs when the engine executes a transition node. It has access to a fixed set of objects (see [§4](#4-transition-code-reference)). It must set an **outcome** (e.g. `outcome = 'success'` or `set_outcome('success')`).
- **The engine** reads the outcome and follows the connection from that outcome to the next node (state or end). It does not use return values or arbitrary state changes for routing.

**Golden rule:** *Python code decides what happened (the outcome); the graph decides where to go next.*

### 2.2 Node Types

| Type | Role |
|------|------|
| **Start** | Single entry point; the first node executed when the instance is started. |
| **State** | Stable node where the FSM waits for an event. Has a list of events; each event is connected to a transition. |
| **Transition** | Contains Python code. When run, the code sets an outcome; outcomes are connected to states or End. |
| **End** | Terminal node; instance state becomes `ended`. |
| **Global state** | Optional single state whose events are available from any current state (current state handlers take priority). |

### 2.3 Execution States

An FSM instance has an execution state: `init`, `running`, `paused`, `ended`, `error`. Only when it is `running` (or `paused` with a `next_node_id`) can it process events and advance.

---

## 3. Core Components

### 3.1 `fsm.definition` — The Blueprint

- **`json_ui_schema`:** Visual layout (nodes, positions, connections). Managed by the OWL designer.
- **`json_compiled_definition`:** Executable structure (start node, nodes, events, outcomes, global state). Generated from the UI schema on save.
- **`state`:** Lifecycle of the definition: `draft`, `test`, `production`.
- **`is_verified`:** Set by “Validate”; checks that all nodes have required connections.

### 3.2 `fsm.instance` — The Running Workflow

- **`state`:** Execution state (`init`, `running`, `paused`, `ended`, `error`).
- **`current_state_id`:** Node ID of the state where the FSM is waiting for an event.
- **`next_node_id`:** When paused mid-chain, the next transition node to execute.
- **`instance_variables`:** JSON dict of persistent variables (updated when a chain reaches a state or end).
- **`intermediate_variables`:** JSON dict used during a transition chain; when the chain completes, its content is written to `instance_variables`.

### 3.3 `fsm.timer` — Scheduled Events

- **`trigger_at`:** When the event should be sent.
- **`json_event`:** JSON-serialized event payload.
- **`fsm_instance_id`:** Target instance. When `trigger_at` is reached, the timer processor sends the event and deletes the timer.

---

## 4. Transition Code Reference

Transition code is the Python snippet executed when the engine runs a **transition** node. It runs in a restricted environment: only the names listed below are available. You **must** set an outcome so the engine can route to the next node.

### 4.1 Objects Available in Transition Code

The following names are injected as globals when your code runs. No other built-ins or imports are guaranteed.

| Name | Type | Description |
|------|------|-------------|
| **`variables`** | dict | Read/write. The same dict as the FSM’s intermediate (then instance) variables. Use it to pass data between transitions and to the next state. |
| **`set_outcome`** | callable | `set_outcome('outcome_name')` sets the outcome for this transition. |
| **`log`** | callable | `log("message")` posts a message to the FSM instance’s chatter. |
| **`env`** | `odoo.api.Environment` | Current Odoo environment. Use to access any model: `env['res.partner']`, `env['sale.order']`, etc. |
| **`model`** | `fsm.instance` recordset | The current FSM instance (single record). Use for instance methods (timers, mail, render). |
| **`datetime`** | Odoo field type | Use `datetime.now()` for current UTC datetime. |
| **`date`** | Odoo field type | Use `date.today()` for current date. |
| **`timedelta`** | `datetime.timedelta` | For date/datetime arithmetic. |
| **`user`** | `res.users` | Current user (`env.user`). |
| **`company`** | `res.company` | Current company (`env.company`). |

**Setting the outcome:** Either assign `outcome = 'outcome_name'` or call `set_outcome('outcome_name')`. The engine reads `variables['outcome']` (default `'__default__'`) and looks up the next node from the transition’s outcome map in the graph.

### 4.2 Event Data

When the transition was triggered by an event, the event dict is stored in `variables['event']` before your code runs (e.g. `{'name': 'payment_received', 'amount': 100}`). Use it read-only:

```python
event = variables.get('event', {})
event_name = event.get('name')
amount = event.get('amount', 0)
```

### 4.3 Instance Methods (on `model`)

You can call these on the FSM instance (`model`) from transition code:

| Method | Description |
|--------|-------------|
| `model.start_timer(event_dict, delay=seconds)` | Schedule an event to be sent after `delay` seconds. |
| `model.start_timer(event_dict, at=datetime)` | Schedule an event at a specific datetime. |
| `model.stop_timer(event_name)` | Cancel timers with the given event name for this instance. |
| `model.stop_all_timers()` | Cancel all timers for this instance. |
| `model.log(message)` | Post a message to the instance chatter (same as global `log(message)`). |
| `model.render_page(page_name, **params)` | Render an FSM page template by name (definition must have the page). |
| `model.action_send_template_mail(target_record, template_name, subject=None)` | Render and send the definition’s mail template; `target_record` must support `message_notify` (e.g. a record with mail.thread). |

### 4.4 Safety and Restrictions

- **No routing via return:** The next node is determined only by the outcome and the graph.
- **No arbitrary imports:** Only the names in the table above are available. Use `env` and `model` for Odoo data and services.
- **Execution context:** Code runs in the same process as the FSM engine. Avoid long-running or blocking work; delegate heavy operations elsewhere (e.g. jobs, other models).
- **Persistence:** Updates to `variables` are committed when the transition chain reaches a state or end node. If an exception is raised, the chain is aborted and instance state is not updated.

### 4.5 Transition Code Examples

**Minimal — set outcome only:**

```python
outcome = 'success'
```

**Using event data:**

```python
event = variables.get('event', {})
approved = event.get('approved', False)
outcome = 'approve' if approved else 'reject'
```

**Reading and writing variables:**

```python
order_id = variables.get('order_id')
variables['processed_at'] = datetime.now().isoformat()
if order_id:
    order = env['sale.order'].browse(order_id)
    if order.exists():
        order.write({'state': 'processing'})
outcome = 'success'
```

**Logging:**

```python
log("Starting validation.")
log(f"Order ID: {variables.get('order_id')}")
outcome = 'next'
```

**Timer (e.g. timeout in 5 minutes):**

```python
model.start_timer({'name': 'timeout'}, delay=300)
outcome = 'waiting'
```

**Timer at a specific time:**

```python
model.start_timer({'name': 'reminder'}, at=datetime.now() + timedelta(hours=1))
outcome = 'scheduled'
```

**Send mail using a definition template:**

```python
partner_id = variables.get('partner_id')
if partner_id:
    partner = env['res.partner'].browse(partner_id)
    if partner.exists():
        model.action_send_template_mail(partner, 'Order Confirmation')
outcome = 'sent'
```

**Using a related business record stored in variables:**

```python
# Assume variables['res_model'] and variables['res_id'] were set when starting the FSM
res_model = variables.get('res_model')
res_id = variables.get('res_id')
if res_model and res_id:
    record = env[res_model].browse(res_id)
    if record.exists():
        record.write({'state': 'in_progress'})
outcome = 'next'
```

A compact quick reference is in [docs/TRANSITION_CODE_REFERENCE.md](docs/TRANSITION_CODE_REFERENCE.md).

---

## 5. Integration with Business Models

### 5.1 Polymorphic Relationship (Recommended for Existing Models)

Attach an FSM instance to any model via a Many2one and optional `numa_poly` integration:

```python
from collections import OrderedDict
from odoo import models, fields, api

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'mail.thread', 'mail.activity.mixin']

    _depend_models = OrderedDict({
        'fsm.instance': 'order_fsm_id'
    })

    order_fsm_id = fields.Many2one('fsm.instance', string='Order Workflow', readonly=True)

    def action_confirm(self):
        res = super().action_confirm()
        if not self.order_fsm_id:
            fsm_def = self.env['fsm.definition'].search([
                ('name', '=', 'Order Processing'),
                ('state', '=', 'production')
            ], limit=1)
            if fsm_def:
                self.order_fsm_id = self.env['fsm.instance'].create({
                    'definition_id': fsm_def.id,
                    'name': f'ORDER-{self.name}',
                })
                self.order_fsm_id.start()
        if self.order_fsm_id:
            self.order_fsm_id.send_event({'name': 'order_confirmed'})
        return res

    def action_cancel(self):
        res = super().action_cancel()
        if self.order_fsm_id:
            self.order_fsm_id.send_event({'name': 'cancel'})
        return res
```

When creating the instance, you can pass business context in initial variables (e.g. via a custom create or a first transition): store `order_id`, `partner_id`, `res_model`/`res_id`, etc., and use them in transition code as in §4.5.

### 5.2 Sending Events from Outside the FSM

From controllers, crons, or other models:

```python
instance.send_event({
    'name': 'payment_received',
    'payment_id': payment_id,
    'amount': amount,
})
```

Events are processed asynchronously via `numa_asynch_exec`. Status can be monitored in `numa.asynch.job`.

---

## 6. Getting Started

### 6.1 Install Dependencies

Ensure these modules are installed: `numa_poly`, `numa_asynch_exec`, `mail`, `website`.

### 6.2 Create an FSM Definition

1. Go to **FSM → Definitions** and create a new record.
2. Open the **Designer** tab.
3. Add nodes: double-click the canvas for State, Transition, End; ensure there is exactly one Start.
4. For each **state**, define **events** (names) and connect each event to a **transition**.
5. For each **transition**, add **Python code** that sets an outcome, and add **outcomes** (e.g. `success`, `failure`). Connect each outcome to a state or End.
6. Save; the definition is compiled to `json_compiled_definition`.
7. Use **Validate** to check connectivity, then set the definition to Test or Production.

### 6.3 Create and Start an Instance

From your model or directly:

```python
instance = env['fsm.instance'].create({
    'definition_id': definition.id,
    'name': 'MY-INSTANCE-001',
})
instance.start()
```

Optionally pass initial context via variables in a first transition (e.g. from Start to a transition that sets `variables['order_id'] = ...` from a linked record).

### 6.4 Send Events

```python
instance.send_event({'name': 'event_name', 'key': 'value'})
```

---

## 7. Advanced Features

### 7.1 Global State

One state in the definition can be marked as **global** (`is_global: true` in the node). Its events are then available from any current state. If the same event exists in the current state and in the global state, the current state’s handler is used. Use global state for events like `timeout`, `cancel`, or `abort`.

### 7.2 Timers

- **Start:** In transition code, call `model.start_timer(event_dict, delay=seconds)` or `model.start_timer(event_dict, at=datetime)`.
- **Stop:** `model.stop_timer('event_name')` or `model.stop_all_timers()`.
- Timers are processed every second by a task started via `post_init_hook`. When `trigger_at` is reached, the event is sent to the instance and the timer is removed.

### 7.3 Variable Lifecycle

- **Instance variables:** Persisted when a transition chain reaches a state or end node. Available in the next transition as the initial `variables` (or in `instance_variables` on the instance).
- **Intermediate variables:** Used only during the current chain; after the chain completes, they overwrite `instance_variables` for the new state.

### 7.4 Debugging

- **Step-by-step:** Set the instance’s `debug_mode` to `step_by_step`; execution pauses after each transition. Use “Next Step” / “Continue” in the UI.
- **Breakpoints:** Mark a transition as a breakpoint in the definition; execution pauses when that transition is about to run.
- **Logs:** Use `log("message")` in transition code; messages appear in the instance’s chatter.

---

## 8. Examples

### 8.1 Document Approval

- States: Draft → (submit) → Pending Review → (approve → Approved | reject → Rejected). Global event: cancel → Cancelled.
- Store `document_id` (or `res_model`/`res_id`) in variables when starting. In transitions, load the document with `env[res_model].browse(res_id)` and update its state or post messages.

### 8.2 Order Processing with Payment

- When the order is confirmed, create an FSM instance and call `start()`; send `order_confirmed`. Store `order_id` (and optionally `partner_id`) in the first transition or when creating the instance (e.g. via a default or a start transition).
- When payment is received (webhook or button), call `instance.send_event({'name': 'payment_received', 'amount': ..., 'payment_id': ...})`. Transition code can update the order and set outcome `success` or `failed`.

### 8.3 Timeout with Timer

- In a “Waiting” state, a transition can start a timer: `model.start_timer({'name': 'timeout'}, delay=600)` and set outcome `waiting`. When the timer fires, the instance receives the event `timeout`. Handle it in the same state (e.g. “go to expired”) or in the global state.

---

## 9. Best Practices

- **Design:** Keep states and outcomes clearly named; document transition code and variable usage.
- **Outcome:** Always set exactly one outcome in every transition; ensure that outcome is connected in the graph.
- **Variables:** Store IDs and small data in `variables`; avoid storing large objects. Use `res_model`/`res_id` when the same FSM can work with different models.
- **Events:** Include relevant payload in the event dict; use it read-only in transition code.
- **Timers:** Stop timers when they are no longer needed (e.g. when leaving the state that started them).
- **Errors:** Use try/except and `log()` in transition code where useful; uncaught exceptions abort the chain and set the instance to `error`.
- **Testing:** Use a Test definition and step-by-step debugging before promoting to Production.

---

## 10. Troubleshooting

| Issue | Checks |
|-------|--------|
| Events not processed | Confirm instance is `running`; check `numa.asynch.job` for pending/failed jobs; ensure `numa_asynch_exec` is installed and workers are running. |
| Wrong or no outcome | Ensure transition code sets `outcome` (or `set_outcome(...)`); ensure that outcome is connected to a state or end in the diagram. |
| Timers not firing | Verify the timer processor task is running (e.g. `numa.asynch.job` for `fsm.timer._process_timers`); check `trigger_at` is in the past; confirm `post_init_hook` ran. |
| Global event not found | Ensure one state has `is_global: true` and the event is defined there; event names are case-sensitive; current state handler takes priority. |
| Transition code error | Check syntax and that only injected globals are used; use `log()` to inspect variables; run in step-by-step mode to isolate the failing transition. |
| Variables not persisting | Variables are written to the instance only when the chain reaches a state or end node; if the chain raises an exception, updates are not saved. |

---

## Additional Resources

- [README.md](README.md) — Overview and documentation index.
- [docs/TRANSITION_CODE_REFERENCE.md](docs/TRANSITION_CODE_REFERENCE.md) — Quick reference for transition code globals and methods.
- [numa_fsm_documentation.md](numa_fsm_documentation.md) — Legacy schema and graph-first notes.
- **Dependencies:** `numa_poly`, `numa_asynch_exec`, Odoo `mail`, `website`.

**Module:** numa_fsm · **Version:** 18.0
