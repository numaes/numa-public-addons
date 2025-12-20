# Numa FSM: Visual Finite State Machine Engine

`numa_fsm` provides a powerful, visual, and transactional engine for creating and executing Finite State Machines (FSMs) within Odoo. It replaces the legacy text-based definition with a modern, interactive graphical editor built with OWL.

## Key Features

- **Visual Editor:** A drag-and-drop interface to design complex workflows by connecting states, transitions, and decision nodes.
- **Transactional Execution:** The engine ensures that a chain of transitions is atomic. The instance's state is only updated upon successful completion, preventing data corruption.
- **Live Debugging:** A visual debugger integrated into the FSM instance form, allowing developers to see the current state of execution directly on the diagram.
- **Step-by-Step Execution:** Control the flow with "Next Step" and "Continue" buttons, and inspect variables at each stage.
- **Breakpoints:** Mark any transition as a breakpoint to pause execution automatically for inspection.
- **Polymorphic by Design:** Built on `numa_poly`, allowing any Odoo model to become a state machine.

## Architecture Overview

### 1. `fsm.definition` - The Blueprint

This model stores the FSM's design.

- **`json_ui_schema`:** A JSON field containing the visual representation of the diagram (node positions, connections, etc.), managed by the OWL editor.
- **`json_compiled_definition`:** A read-only JSON field automatically generated from the UI schema. It contains a structured, optimized representation of the FSM used by the execution engine. This ensures a clean separation between presentation and logic.

### 2. `fsm.instance` - The Execution

This model represents a running instance of a state machine.

- **`state`:** The execution state (`init`, `running`, `paused`, `ended`, `error`).
- **`current_state_id`:** The ID of the `state` node where the FSM is currently waiting for an event.
- **`next_node_id`:** The ID of the next `transition` node to be executed when the FSM is paused.
- **`instance_variables`:** A JSON field holding the persistent state (variables) of the instance.
- **`intermediate_variables`:** A temporary JSON field to hold variables during a transition chain, enabling transactional execution and debugging.

### 3. The Execution Engine (`_execute_chain`)

- **Transactional Loop:** When an event is triggered, the engine starts a chain of transitions. It operates on a copy of the instance variables (`intermediate_variables`).
- **Atomic Commits:** The main `instance_variables` are only updated if the entire chain completes successfully and reaches a new `state` or `end` node.
- **Error Handling:** If any exception occurs, the chain is aborted, the error is logged to the chatter, and the instance state is rolled back, preserving data integrity.

## How to Use

1.  **Create a Definition:**
    - Go to the FSM Definitions menu.
    - Create a new record.
    - Use the "Designer" tab to build your workflow visually:
        - **Double-click** on the canvas to create new nodes (State, Transition, End).
        - **Double-click** on a node to edit its properties (name, code, events, outcomes).
        - **Drag** from a node's output port to another's input port to create a connection.
2.  **Instantiate the FSM:**
    - In your target model (e.g., `conversation.session`), create a `Many2one` field to `fsm.instance`.
    - On a specific action (e.g., creating a new session), create a new `fsm.instance` record, linking it to your FSM definition.
3.  **Execute and Debug:**
    - Call the `start()` method on the instance to begin execution.
    - Use the `process_event({'name': 'event_name', ...})` method to trigger events.
    - Open the instance's form view to see the live state on the diagram, inspect variables, and use the debug controls.
