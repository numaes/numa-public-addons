# Numa FSM — Transition Code Quick Reference

Transition code is Python executed when the engine runs a **transition** node. It runs in a restricted environment: only the names listed below are available. The code **must** set an outcome so the engine can choose the next state.

---

## 1. Available globals (injected into transition code)

| Name | Type | Description |
|------|------|-------------|
| `variables` | dict | Read/write. Same dict as the FSM’s intermediate (then instance) variables. Use it to pass data between transitions and to the next state. |
| `set_outcome` | callable | `set_outcome('outcome_name')` sets the outcome for this transition. Alternative: assign `outcome = 'outcome_name'` in code. |
| `log` | callable | `log("message")` posts a message to the FSM instance’s chatter. |
| `env` | `odoo.api.Environment` | Current Odoo environment. Use to access any model: `env['res.partner']`, `env['sale.order']`, etc. |
| `model` | `fsm.instance` recordset | The current FSM instance (single record). Use for instance methods (timers, mail, render). |
| `datetime` | Odoo field type | Use `datetime.now()` for current UTC datetime. |
| `date` | Odoo field type | Use `date.today()` for current date. |
| `timedelta` | `datetime.timedelta` | For date/datetime arithmetic. |
| `user` | `res.users` recordset | Current user (`env.user`). |
| `company` | `res.company` recordset | Current company (`env.company`). |

---

## 2. Setting the outcome

The engine reads the outcome from the `variables` dict after your code runs. Map each outcome to a target state in the diagram (transition outcomes → connections to states/end).

**Option A — variable assignment:**

```python
outcome = 'success'
```

**Option B — helper:**

```python
set_outcome('success')
```

If the code does not set `outcome`, the engine uses `'__default__'`. Ensure that outcome exists in the transition’s outcome map in the graph.

---

## 3. Accessing event data

When the transition was triggered by an event, the event dict is placed in `variables['event']` before the code runs (e.g. `{'name': 'payment_received', 'amount': 100}`). Use it read-only:

```python
event = variables.get('event', {})
event_name = event.get('name')
amount = event.get('amount', 0)
```

---

## 4. Instance methods (on `model`)

Call these on the FSM instance (`model`) from transition code.

| Method | Purpose |
|--------|---------|
| `model.start_timer(event_dict, delay=seconds)` | Schedule an event to be sent after `delay` seconds. |
| `model.start_timer(event_dict, at=datetime)` | Schedule an event at a specific datetime. |
| `model.stop_timer(event_name)` | Cancel timers with the given event name. |
| `model.stop_all_timers()` | Cancel all timers for this instance. |
| `model.log(message)` | Post a message to the instance chatter (same as global `log(message)`). |
| `model.render_page(page_name, **params)` | Render an FSM page template by name (definition must link the page). |
| `model.action_send_template_mail(target_record, template_name, subject=None)` | Render and send the definition’s mail template to the target record (e.g. partner). |

**Timer example:**

```python
# Fire 'timeout' in 5 minutes (timedelta is available as a global)
model.start_timer({'name': 'timeout'}, delay=300)
# Or at a specific time
model.start_timer({'name': 'reminder'}, at=datetime.now() + timedelta(hours=1))
```

---

## 5. Working with related business records

Store identifiers in `variables` when starting the FSM or in earlier transitions (e.g. `order_id`, `partner_id`, `res_model`, `res_id`). In transition code, load the record via `env`:

```python
order_id = variables.get('order_id')
if order_id:
    order = env['sale.order'].browse(order_id)
    if order.exists():
        order.write({'state': 'processing'})
outcome = 'success'
```

---

## 6. Safety and restrictions

- **No `return` for routing:** The next node is determined only by the outcome and the graph. Do not rely on return values.
- **No arbitrary imports:** Only the names in the table above are available. Use `env` and `model` to access Odoo data and services.
- **Execution context:** Code runs in the same process as the FSM engine; avoid long-running or blocking operations. Heavy work should be delegated (e.g. via jobs or other models).
- **Persistence:** Changes to `variables` are persisted when the transition chain reaches a state or end node. Exceptions abort the chain and leave instance state unchanged.

---

## 7. Minimal examples

**Simple outcome:**

```python
variables['processed'] = True
outcome = 'success'
```

**From event data:**

```python
event = variables.get('event', {})
ok = event.get('approved', False)
outcome = 'approve' if ok else 'reject'
```

**With logging:**

```python
log("Processing step.")
order_id = variables.get('order_id')
if order_id:
    log(f"Order ID: {order_id}")
outcome = 'next'
```

**Timer then wait:**

```python
model.start_timer({'name': 'timeout'}, delay=600)
outcome = 'waiting'
```

For more examples and integration patterns, see [USER_GUIDE.md](../USER_GUIDE.md).
