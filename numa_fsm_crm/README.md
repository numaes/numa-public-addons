# Numa FSM CRM

Integration of Finite State Machine capabilities into CRM Leads.

## Overview

This module transforms CRM leads into FSM instances, allowing automated workflows and bot-driven lead processing. Each lead can be assigned a bot (FSM definition) that controls the lead's workflow automatically.

## Key Features

### 1. Polymorphic Lead Model
- `crm.lead` is extended to be polymorphic with `_depend_models = {'fsm.instance': 'fsm_instance_id'}`
- Leads can inherit FSM instance capabilities without modifying core CRM models

### 2. CRM Bots
- `crm.bot` model extends `fsm.definition` (similar to `conversation.bot`)
- Bots are FSM definitions specifically designed for CRM workflows
- Bots can be created and configured in CRM Settings

### 3. Lead-to-FSM Conversion
- Leads can be converted into FSM instances by assigning a bot
- FSM starts automatically when bot is assigned (if definition is in production)
- Manual start/stop/pause/resume controls available

### 4. FSM Control Interface
- New notebook page "FSM Workflow" in lead form
- Shows current FSM state and execution status
- Provides controls for:
  - Start FSM
  - Pause FSM (for debugging)
  - Resume FSM
  - Next Step (step-by-step execution)
- Visual FSM diagram showing current state
- FSM variables viewer for debugging

### 5. Visual State Indicator
- Miniature FSM diagram widget showing current state
- Highlights active node in the diagram
- Updates in real-time as FSM progresses

## Architecture

### Models

#### `crm.bot`
Extends `fsm.definition` using polymorphic inheritance:
- `_depend_models = {'fsm.definition': 'fsm_definition_id'}`
- Default type: `'crm_bot'`
- Managed in CRM Settings menu

#### `crm.lead`
Extended with FSM capabilities:
- `_inherit = ['crm.lead', 'fsm.instance']`
- `_depend_models = {'fsm.instance': 'fsm_instance_id'}`
- Fields:
  - `bot_id`: Many2one to `crm.bot`
  - `definition_id`: Many2one to `fsm.definition` (computed from bot)
  - `bot_state`: Current state label (computed)
  - `has_fsm`: Boolean indicating active FSM

### Import Order

**Critical**: The import order in `models/__init__.py` is important:
```python
# crm_lead must be imported first to set up _depend_models
from . import crm_lead
from . import crm_bot
```

This ensures that `_depend_models` is set up before `fsm.instance` is used.

## Usage

### Creating a CRM Bot

1. Go to **CRM > Configuration > CRM Bots (FSM)**
2. Create a new bot
3. Design the FSM workflow using the diagram editor
4. Set state to "Production" when ready

### Assigning a Bot to a Lead

1. Open a CRM lead
2. Click "Assign Bot" button (if no bot assigned)
3. Select a bot from the list
4. FSM will start automatically if bot is in production state

### Controlling FSM Execution

1. Open a lead with an assigned bot
2. Go to "FSM Workflow" notebook page
3. Use controls to:
   - **Start FSM**: Begin execution
   - **Pause FSM**: Pause at next breakpoint (for debugging)
   - **Resume FSM**: Continue execution
   - **Next Step**: Execute one step at a time

### Viewing FSM State

- The "FSM Workflow" page shows:
  - Current state label
  - Execution state (init/running/paused/ended)
  - Current state node ID
  - Next node to execute
  - Visual diagram with active node highlighted
  - FSM variables (for debugging)

## Dependencies

- `crm`: CRM module
- `numa_fsm`: FSM engine
- `numa_poly`: Polymorphic inheritance
- `mail`: For chatter integration

## Technical Notes

### Polymorphic Inheritance

The module uses `numa_poly` for polymorphic inheritance:
- `crm.lead` inherits from both `crm.lead` (base) and `fsm.instance`
- `crm.bot` inherits from `fsm.definition`
- This allows extending models without modifying core Odoo code

### FSM Lifecycle

1. **Init**: Lead created with bot assigned
2. **Auto-start**: FSM starts automatically if definition is in production
3. **Running**: FSM executes workflow
4. **Paused**: FSM paused for debugging (step-by-step mode)
5. **Ended**: FSM workflow completed

### State Computation

The `bot_state` field computes the human-readable label from the FSM definition's JSON schema by matching the current state node ID with the diagram nodes.

## License

LGPL-3
