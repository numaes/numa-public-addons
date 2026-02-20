# Numa FSM — Graph-First Definition and Schema

This document describes the graph-first paradigm and the structure of the UI and compiled definitions. For day-to-day usage, transition code reference, and integration, see [USER_GUIDE.md](USER_GUIDE.md) and [docs/TRANSITION_CODE_REFERENCE.md](docs/TRANSITION_CODE_REFERENCE.md).

---

## Overview

Numa FSM uses a **graph-first** design: the visual diagram defines the topology and routing; Python code in transitions only decides the **outcome**. The engine then uses the graph to determine the next state or end node from that outcome.

**Principle:** *Python code decides what happened (the outcome); the graph decides where to go next.*

---

## Field Reference

### `json_ui_schema`

Stores the visual layout and topology for the OWL editor: nodes (with positions, types, labels, code, events, outcomes) and connections.

Example shape:

```json
{
  "nodes": [
    {"id": "state_init", "x": 40, "y": 200, "type": "state", "label": "init"},
    {"id": "dec_start", "x": 260, "y": 190, "type": "transition", "label": "start"},
    {"id": "state_done", "x": 460, "y": 200, "type": "state", "label": "done"}
  ],
  "connections": [
    {"fromNodeId": "state_init", "fromPortName": "event_go", "toNodeId": "dec_start"},
    {"fromNodeId": "dec_start", "fromPortName": "success", "toNodeId": "state_done"}
  ]
}
```

Node types: `start`, `state`, `transition`, `end`. A state can have `is_global: true` (at most one per definition). Transitions have `code` (Python) and `outcomes` (port name → target node id).

### `json_compiled_definition`

Read-only; generated from `json_ui_schema` on save. Used by the execution engine. Structure (conceptual):

```json
{
  "start_node_id": "<id of start node>",
  "global_state_id": "<id of global state or null>",
  "nodes": {
    "<node_id>": {
      "id": "...",
      "type": "start|state|transition|end",
      "label": "...",
      "code": "...",
      "events": [{"name": "...", "target_transition_id": "..."}],
      "outcomes": {"<outcome_name>": "<target_node_id>"},
      "is_global": false,
      "is_breakpoint": false
    }
  }
}
```

---

## Using the Engine

1. In **fsm.definition**, design the graph in the Designer tab and save (compilation is automatic).
2. Create an **fsm.instance** with that definition and call `start()`.
3. At runtime, send events with `instance.send_event({"name": "event_name", ...})`. The engine finds the handler (current state or global state), runs the transition code, reads the outcome, and moves to the connected state or end.

---

## Backward Compatibility

If the module is used with legacy text-based definitions, the engine can fall back to a compiled definition derived from `text_definition` when `json_compiled_definition` is empty. Prefer the visual designer and `json_ui_schema` for new workflows.

---

**See also:** [USER_GUIDE.md](USER_GUIDE.md), [docs/TRANSITION_CODE_REFERENCE.md](docs/TRANSITION_CODE_REFERENCE.md), [README.md](README.md).
