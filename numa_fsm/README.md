# Numa FSM — Finite State Machine Engine for Odoo

**Odoo 18.0** | LGPL-3 | NUMA Extreme Systems

---

## 1. Overview

**Numa FSM** is a finite state machine (FSM) engine for Odoo that combines a visual, graph-first designer with Python transition code. Workflows are designed in a drag-and-drop diagram (states, transitions, events, outcomes); all decision logic lives in short Python snippets that run in a controlled environment.

**Core principle:** The graph defines *where* the workflow can go; the transition code defines *what* happened (the outcome). The engine then routes to the state mapped to that outcome.

### 1.1 Key features

| Feature | Description |
|--------|-------------|
| **Visual designer** | OWL-based canvas: states, transitions, start/end nodes; connections define events and outcomes. |
| **Outcome-based execution** | Transition code sets an `outcome` (or uses `set_outcome()`); the graph maps outcomes to target states. |
| **Asynchronous events** | Events are processed via `numa_asynch_exec` (persisted, retriable, non-blocking). |
| **Timers** | Schedule events to fire at a given time; timer processor runs every second. |
| **Global state** | One optional global state can define events available in *any* current state. |
| **Transactional execution** | A chain of transitions runs on a copy of variables; instance state is updated only when the chain reaches a state or end node. |
| **Debugging** | Step-by-step mode, breakpoints on transitions, and chatter logs. |
| **Polymorphic integration** | Built on `numa_poly`; any model can hold an FSM instance via a Many2one. |

### 1.2 Dependencies

- **Odoo modules:** `base`, `mail`, `numa_poly`, `numa_asynch_exec`, `website`  
- **License:** LGPL-3  

---

## 2. Documentation index

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | This file: overview and quick links. |
| [USER_GUIDE.md](USER_GUIDE.md) | End-to-end user and developer guide: concepts, designer, **transition code** (objects, safety, examples), integration, timers, debugging. |
| [docs/TRANSITION_CODE_REFERENCE.md](docs/TRANSITION_CODE_REFERENCE.md) | Quick reference: globals available in transition code, instance methods, and minimal examples. |
| [numa_fsm_documentation.md](numa_fsm_documentation.md) | Legacy/graph-first paradigm and schema notes. |

---

## 3. Quick start

1. **Create an FSM definition:** FSM → Definitions → New → Designer tab. Add nodes (State, Transition, End), connect them, and add Python code to each transition. Set **outcomes** on transitions and connect each outcome to a target state (or end).
2. **Validate and promote:** Use “Validate” to check connectivity, then set the definition to Test or Production.
3. **Create an instance:** From your model (or directly), create an `fsm.instance` with `definition_id` and call `start()`.
4. **Send events:** Call `instance.send_event({'name': 'event_name', ...})`; events are processed asynchronously. In transition code, use the provided globals (`model`, `env`, `variables`, `log`, `set_outcome`, etc.) and set `outcome` (or `set_outcome('...')`) so the engine can route correctly.

For transition code rules, available objects, and examples, see [USER_GUIDE.md § Transition code](USER_GUIDE.md#4-transition-code-reference) and [docs/TRANSITION_CODE_REFERENCE.md](docs/TRANSITION_CODE_REFERENCE.md).

---

## 4. License and author

- **Author:** NUMA Extreme Systems  
- **Website:** [https://www.numaes.com](https://www.numaes.com)  
- **License:** LGPL-3  
