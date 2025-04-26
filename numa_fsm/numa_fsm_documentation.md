# NUMA Finite State Machine (FSM) Module Documentation

## Overview
The NUMA Finite State Machine (FSM) module is an Odoo application that provides a framework for implementing finite state machines in Odoo. It allows for the definition of workflows with states, events, and transitions, and provides a mechanism for executing these workflows.

## Key Components

### FSM Definition
The `FSMDefinition` model is used to define finite state machines. Each FSM definition includes:
- A name
- A text definition that defines the states, events, and transitions of the FSM
- Support for inheritance through parent-child relationships
- Associated page templates and mail templates

The text definition is compiled into a JSON representation that is used at runtime. The compilation process is handled by the `compile_definition` function, which parses the text definition and creates a structured representation of the FSM.

### FSM Instance
The `FSMInstance` model represents a running instance of an FSM. Each instance includes:
- A reference to the FSM definition
- The current state of the instance
- A queue of events to be processed
- Instance-specific values stored as JSON
- A state field indicating whether the instance is initialized, running, stopped, or ended

Key methods of the FSMInstance class include:
- `start()`: Initializes the FSM instance by executing the start code from the FSM definition
- `end()`: Ends the FSM instance by stopping all timers and marking it as ended
- `process_event(event, env)`: Processes an event by finding the appropriate event handler in the FSM definition and executing it
- `send_event(event)`: Sends an event to potentially multiple receivers
- `change_state(new_state)`: Changes the current state of the FSM instance
- `start_timer(event, delay, at)`: Starts a timer that will trigger an event after a specified delay or at a specified time
- `stop_timer(event_name)`: Stops a timer for a specific event
- `set_page(page_name)`: Sets the current page of the FSM instance

### Supporting Models

#### WorkFlowMailTemplate
The `WorkFlowMailTemplate` model is used to define email templates that can be used in workflows. Each template includes:
- A name
- A subject
- An HTML body
- Attachments

#### WorkFlowPageTemplate
The `WorkFlowPageTemplate` model is used to define page templates that can be used in workflows. Each template includes:
- A name
- An HTML body

#### FSMFormInput
The `FSMFormInput` model is a transient model used for form inputs in workflows.

### Web Interface
The module provides a web interface for interacting with FSMs:
- The `FSMController` provides a route for displaying FSM page templates
- The `WebsiteForm` controller extends the standard Odoo WebsiteForm controller to handle form submissions for the FSM module

## Usage

### Defining an FSM
To define an FSM, create a new record in the `fsm.definition` model and provide a text definition. The text definition follows a specific syntax that defines the states, events, and transitions of the FSM.

### Creating an FSM Instance
To create an FSM instance, create a new record in the `fsm.instance` model and specify the FSM definition. The instance can then be started, which will execute the start code from the FSM definition.

### Processing Events
Events can be sent to an FSM instance using the `send_event` method. The FSM instance will process the event according to the FSM definition, potentially changing state and executing code.

### Ending an FSM Instance
An FSM instance can be ended using the `end` method, which will stop all timers and mark the instance as ended.

## Technical Details

### Event Processing
Events are processed by finding the appropriate event handler in the FSM definition and executing it. The event handler can change the state of the FSM instance, send new events, start timers, and perform other actions.

### Timers
The module supports timers that can trigger events after a specified delay or at a specified time. Timers are implemented using the `fsm.timer` model.

### Inheritance
FSM definitions support inheritance through parent-child relationships. A child FSM definition can extend a parent FSM definition, inheriting its states, events, and transitions.

### Logging
The module supports logging of FSM instance activities, including state changes, event processing, and timer operations. Logging can be enabled or disabled for each FSM instance.

## Conclusion
The NUMA FSM module provides a powerful framework for implementing finite state machines in Odoo. It allows for the definition of complex workflows with states, events, and transitions, and provides a mechanism for executing these workflows. The module is highly customizable and can be extended to support various use cases.