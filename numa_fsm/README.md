NUMA FSM — Graph-First Finite State Machines for Odoo

Overview
`numa_fsm` is a Finite State Machine (FSM) engine for Odoo that combines an intuitive visual designer with the full power and flexibility of Python. Developers and functional users can design the topology of a workflow visually, while keeping all decision logic in concise Python snippets.

This release introduces the Graph-First paradigm with an Outcome-based execution engine: the Python code determines what happened (the outcome), and the visual graph decides where to go next (the target state). This separation makes workflows easier to reason about, maintain, and evolve.

Visual Designer
A new OWL field widget (`fsm_diagram`) provides a Canvas to build FSMs via Drag & Drop:
- Add States (rectangles) and Decisions/Transitions (diamonds)
- Connect State → Decision to model an event
- Connect Decision → State to model an outcome mapping
- Pan and Zoom to navigate complex graphs
- Edit properties in a sidebar: state name/subtype, decision event name, Python code, and outcomes

The designer persists the visual layout (positions, zoom, connections) in the model field `json_ui_schema`. A Save action also compiles the visual graph into an executable logic schema (`json_logic_schema`) consumed by the backend engine.

Logic & Outcomes (The Key Concept)
Separation of concerns:
- The Graph describes topology and routing between states.
- Python code analyzes data and sets an outcome string.
- The Graph maps the outcome to a destination state.

The Golden Rule:
"Python code decides WHAT happened (Outcome), the Graph decides WHERE to go."

Example:
```
# OLD WAY (Deprecated)
# instance.change_state('done')

# NEW WAY
# Logic analysis...
if condition:
    outcome = 'success'
else:
    outcome = 'retry'
# The visual graph maps 'success' -> State B, and 'retry' -> State A
```

At runtime, the FSM engine executes the Python snippet associated to the (state, event). The snippet must set an `outcome` variable (or call `set_outcome('name')`). The engine then looks up the `outcomes` mapping for that transition and changes the instance state automatically.

Field Reference
- `json_ui_schema` (Text)
  - Stores visual layout and topology for the editor (nodes, edges, transform).
  - Example shape:
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

- `json_logic_schema` (Text)
  - Stores the executable transitions for the Outcome engine. The editor derives this from the graph.
  - Structure:
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

Using the Engine
1) In your `fsm.definition`, design the graph in the Designer tab and Save.
2) At runtime, call `fsm.instance.consume_event({"name": "your_event"})`.
3) The engine executes the transition code for the current state and event. Based on `outcome`, it routes to the mapped target state.

Backward Compatibility
If `json_logic_schema` is empty, the engine falls back to the legacy compiled definition (`json_compiled_definition`), preserving existing workflows while you migrate to Graph-First.
