# NUMA Finite State Machine (FSM) — Updated Documentation

Last updated: 2025-12-07

## Overview
`numa_fsm` is a Finite State Machine (FSM) engine for Odoo that now adopts a Graph‑First paradigm with Outcome‑based execution. Users visually design the topology (states and flow) and keep the decision logic in Python. The code decides what happened (the Outcome) and the graph decides where to go (the target state).

Golden rule: "Python code decides WHAT (Outcome), the Graph decides WHERE (target state)."

## Key Changes
- OWL visual editor as a Field Widget (`fsm_diagram`) with Pan/Zoom, drag & drop, connection creation, and an inspector panel.
- Two JSON fields on `fsm.definition`:
  - `json_ui_schema`: stores the diagram layout (nodes, edges, positions, zoom).
  - `json_logic_schema`: stores executable logic (events, Python code, and outcome→state mappings).
- Hybrid execution engine in `fsm.instance.process_event` that prioritizes `json_logic_schema` and falls back to the legacy compiled scheme if the new logic is not present.

## Main Components

### Model: FSM Definition (`fsm.definition`)
Includes:
- `name`: logical name.
- `json_ui_schema` (Text): visual schema persisted by the editor.
- `json_logic_schema` (Text): executable Outcome‑based schema.
- Legacy compatibility: `text_definition` and `json_compiled_definition` remain for older FSMs and inheritance (`parent_id`).
- Relations to pages (`pages`) and mail templates (`mail_templates`).

#### Data Structures
- `json_ui_schema` example:
```
{
  "nodes": [
    {"id": "state_init", "x": 40, "y": 200, "type": "state", "label": "init"},
    {"id": "dec_start",  "x": 260, "y": 190, "type": "decision", "label": "start"},
    {"id": "state_done", "x": 460, "y": 200, "type": "state", "label": "done"}
  ],
  "edges": [
    {"id": "e1", "source": "state_init", "target": "dec_start", "label": ""},
    {"id": "e2", "source": "dec_start",  "target": "state_done", "label": "success"}
  ],
  "transform": {"x": 0, "y": 0, "k": 1}
}
```

- `json_logic_schema` structure:
```
{
  "states": { "init": {}, "done": {} },
  "transitions": {
    "<source_state>": {
      "<event_name>": {
        "code": "# python...\noutcome = 'success'",
        "outcomes": {
          "success": "<target_state_A>",
          "failure": "<target_state_B>"
        }
      }
    }
  }
}
```

The visual editor generates both JSON documents on save.

### Model: FSM Instance (`fsm.instance`)
Relevant fields:
- `definition_id`: associated definition.
- `current_state`: current state (string).
- `state`: instance lifecycle (`init`, `running`, `stopped`, `ended`).
- `json_instance_values`: execution environment (serialized dict) available as `env` during `exec`.

Key methods:
- `start()`: initializes (keeps legacy start support).
- `consume_event(event)` / `process_event(event, env)`: processes events.
- `change_state(new_state)`, timers, and logging.

#### Outcome‑based Execution
`process_event` performs:
1) Loads `json_logic_schema` from the definition (and walks inheritance if applicable).
2) Looks up the transition by `current_state` (and `all`) and `event['name']`.
3) Executes `code` via `exec`, providing `env`, `fsm_instance`, and the helper `set_outcome(name)`; assigning `outcome = '...'` inside the snippet is also supported.
4) Resolves the `outcome` through the `outcomes` mapping and automatically calls `change_state(target)`.
5) If there is no new logic, it falls back to the legacy mechanism (`json_compiled_definition`).

Error handling: if the code fails or the `outcome` is not mapped, a `UserError` is raised with details; if no outcome is set, a warning is logged and the state remains unchanged.

## Visual Editor (OWL Widget)
Field widget: `fsm_diagram` (assets in `web.assets_backend`).
- Create/edit States (rectangles) and Decisions (diamonds/events).
- Connect State→Decision (event) and Decision→State (outcomes). Optional sugar State→State (outcome `default`).
- Right‑hand inspector to edit state name/subtype, event name, Python code, and the outcomes list.
- Buttons: New State, New Transition/Decision, Save, Delete selected. Shortcuts: Delete (remove), Ctrl/Cmd+S (save).

Save: serializes `json_ui_schema` back to the field and compiles `json_logic_schema` from the graph for the backend engine.

## Typical Usage
1. In `fsm.definition`, the "Designer" tab: draw the flow and edit code in decision nodes.
2. Save: `json_ui_schema` and `json_logic_schema` are generated/updated.
3. At runtime: call `fsm.instance.consume_event({"name": "my_event"})` or `send_event` as appropriate.

Example decision code:
```
if env.get('score', 0) > 10:
    outcome = 'pass'  # or set_outcome('pass')
else:
    outcome = 'fail'
```

The graph maps `pass`→`approved`, `fail`→`rejected`.

## Unit Tests
File: `numa_fsm/tests/test_fsm_engine.py`.
- `test_graph_based_transition`: verifies transition `draft`→`processing` with `verify` and `outcome='ok'`.
- `test_conditional_branching`: branches to `approved` or `rejected` based on `env['score']`.

These tests validate the Outcome‑based engine without relying on the legacy compiled flow.

## Debugging & Observability Suite
Overview
`numa_fsm` ships with an IDE‑like debugger for asynchronous FSM execution. It provides event interception, execution tracing, a pending events queue, and time‑travel simulation. Debugging is built into `fsm.instance` and can be controlled per instance or globally via the FSM definition.

Execution Modes
- Off: normal execution, no interception and no structured logs by default.
- Trace Only: executes events normally and records `fsm.execution.log` entries capturing input/output snapshots, states, and status.
- Step‑by‑Step / Pause: intercepts events before execution, enqueues them into `fsm.debug.event` with `state='pending'`, and returns immediately. Use UI actions to step over (process one), resume, or discard.

Hot‑Fixing (Live Variable Editing)
During a pause, you can edit the instance’s JSON memory (`json_instance_values`) directly from the `fsm.instance` form. The field is editable and uses force‑save so you can correct data “on the fly” before resuming or stepping over.

Circuit Breaker (Global Pause)
On `fsm.definition`, the field `execution_policy` controls a global safety mode:
- Normal Run: standard behavior.
- Pause All Instances: every event for instances of this definition is intercepted into the debug queue (even if instance `debug_mode` is Off). You can still process events via Step Over/Resume because the engine honors a context bypass flag used by these actions.

References
- Models: `fsm.execution.log` (structured logs), `fsm.debug.event` (pending/processed/discarded events)
- Instance actions: `action_debug_step_over`, `action_debug_resume`, `action_debug_discard`
- Views: Debugger tab on `fsm.instance` shows the queue and execution trace.

## Time Travel Simulation (Replay)
The “Simulate Replay” feature allows you to clone an instance at a specific log entry and re‑execute its event safely in a sandbox:
1. From an `fsm.execution.log` entry, click “Simulate Replay”.
2. The system creates a new `fsm.instance` with `is_simulation=True`.
3. It restores `current_state` to the log’s `from_state` and reloads the environment from the `input_snapshot`.
4. It re‑triggers the logged event once, bypassing interceptors and global pause.
5. You are taken to the simulation record to inspect results, logs, and state.

This enables safe validation of fixes or hypotheses without affecting production instances or data.

## Visual Designer — Debug Feedback
The OWL graph widget (`fsm_diagram`) provides visual cues during debugging and simulation when used on `fsm.instance` forms:
- Paused current node: the node matching `current_state` is highlighted with an orange outline when `debug_mode` is `step` or `paused`.
- Error cue: if the last execution status is error (when available), the current node is highlighted in red.
- Simulation cue: when `is_simulation` is true, the canvas shows a blue striped “sandbox” style.

## Compatibility and Migration
- If `json_logic_schema` is empty, the engine uses the existing legacy scheme (`json_compiled_definition`).
- Quick migration: move the code of each legacy transition into the transition's `code` in `json_logic_schema`, and replace direct `change_state(..)` calls with `outcome = '...'` (and define `outcomes` with the target state).

## Security Considerations
Python code is executed with `exec` in a controlled environment (same limits as the legacy engine). Safe utilities are provided (`wrap_module`) as well as context objects (`fsm_instance`, `user`, `company`). Handle external inputs carefully.

## Known Limitations
- Basic semantic validations of the graph (outcomes without visual connections are not prevented; functional review is recommended).
- No advanced snippet editor yet beyond `<textarea>`; Odoo's `CodeEditor` can be integrated in future iterations.

## References
- Module README: `numa_fsm/README.md` — overview, examples, and field references.
- Views: `numa_fsm/views/fsm_views.xml` (Designer tab and widget).
- Widget: `static/src/components/fsm_graph_view/*`.