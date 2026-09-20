# Numa FSM CRM

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). The lead no
longer *is* its FSM instance: it *has* one. That is the one change that shows
from the outside, and it is worth reading before upgrading a database:
see [Migration to Odoo 20.0](#7-migration-to-odoo-200).

---

## 1. Overview

This module drives CRM leads with the FSM engine of `numa_fsm`. A lead can be
given a **bot** —an FSM definition written for CRM workflows— and the module
creates and runs the workflow instance that the bot describes, with start,
pause, resume and step-by-step controls on the lead form.

### 1.1 Compatibility

- **Odoo version:** 20.0
- **Dependencies:** `crm`, `mail`, `numa_fsm`, `numa_poly`
- **License:** LGPL-3

---

## 2. Architecture

### 2.1 `crm.bot`

A CRM bot **is** an FSM definition, through `numa_poly`:

```python
_name = 'crm.bot'
_depend_models = {'fsm.definition': 'fsm_definition_id'}
```

Creating a bot creates its `fsm.definition`; the diagram, the compiled
definition and the production state all live there. New bots get
`type = 'crm_bot'` so they can be told apart from other definitions.

### 2.2 `crm.lead`

A lead **has** an FSM instance:

```python
_name = 'crm.lead'
_inherit = ['crm.lead']

fsm_instance_id = fields.Many2one('fsm.instance', ondelete='set null')
```

| Field | Meaning |
|-------|---------|
| `bot_id` | The bot assigned to the lead. |
| `definition_id` | The FSM definition, computed from the bot but writable on its own. |
| `fsm_instance_id` | The running instance. Empty until the workflow starts. |
| `fsm_state`, `current_state_id`, `next_node_id`, `instance_variables`, `debug_mode` | Related to the instance, so the form asks the lead for them exactly as before. |
| `json_ui_schema` | Related to the **definition**: the diagram can be drawn before there is an instance. |
| `bot_state` | The human-readable label of the current node, computed from the diagram. |
| `has_fsm` | True when the lead has a definition and a running or paused instance. Searchable. |

`_ensure_fsm_instance()` is the only place an instance is created, and it
creates at most one per lead.

### 2.3 Lifecycle

1. A bot is assigned (or a definition is written directly) on a lead.
2. If the definition is in **production**, the module creates the instance and
   calls `start()` on it.
3. The instance runs, pauses at breakpoints or in step-by-step mode, and ends.
4. Deleting the instance leaves the lead intact, and the lead can be started
   again.

---

## 3. Usage

### 3.1 Creating a CRM bot

1. **CRM → CRM Bots (FSM)**.
2. Create the bot and design the workflow with the diagram editor.
3. Set the state to **Production** when it is ready: only production
   definitions start by themselves.

### 3.2 Assigning a bot to a lead

Open the lead and pick a bot in the **CRM Bot** field, or use the **Assign
Bot** button when there is none. The workflow starts on its own if the
definition is in production.

### 3.3 Controlling execution

The **FSM Workflow** page of the lead form appears once the lead has an active
FSM, and offers:

- **Start FSM** — starts a workflow that has not started.
- **Pause FSM** — switches the instance to step-by-step, so it stops at the next node.
- **Resume FSM** — continues a paused instance.
- **Next Step** — executes a single node.

It also shows the diagram with the active node highlighted and, while
debugging, the instance variables.

### 3.4 Finding leads with a workflow

The lead search view adds **With Active FSM** and **With Bot**. The first one
is `has_fsm`, which is computed *and* searchable: without a `search` method an
Odoo computed field cannot be used in a filter, and that alone invalidates the
whole search view, including the standard filters that share it.

---

## 4. Security

`security/ir.access.csv` grants `crm.bot` to employees (`base.group_user`) and
to administrators (`base.group_system`). Leads keep the access rules of `crm`.

---

## 5. Tests

```bash
odoo-bin -d <database> -u numa_fsm_crm --without-demo \
         --test-enable --test-tags=/numa_fsm_crm --stop-after-init
```

Ten tests cover the compute and the search of `has_fsm` (including a lead with
a definition but no instance yet), that the lead form and search views still
validate, that the lead and the instance are two records with independent
lifetimes, that the instance is created exactly once, that the related fields
read through the link, that assigning a production bot starts the workflow, and
that a started workflow refuses to start twice.

### 5.1 Installing on a clean database

`numa_fsm` pulls in `website`, and `website` cannot be installed in the same
run as `numa_poly` (see the note in `numa_poly/doc/`). Install in two passes:

```bash
odoo-bin -d <db> --addons-path=<odoo>/addons -i website,crm --without-demo --stop-after-init
odoo-bin -d <db> --addons-path=<odoo>/addons,<numa-addons> -i numa_fsm_crm --without-demo --stop-after-init
```

---

## 6. Dependencies

| Module | Why |
|--------|-----|
| `crm` | The leads being driven. |
| `numa_fsm` | The FSM engine: definitions, instances, execution. |
| `numa_poly` | Polymorphic inheritance for `crm.bot`. |
| `mail` | Chatter and tracking on the bot field. |

---

## 7. Migration to Odoo 20.0

### 7.1 The lead has an instance instead of being one

Up to 18.0 the lead declared `_inherit = ['crm.lead', 'fsm.instance']` and
became the instance, with no separate record. That stopped linearising in
20.0: `fsm.instance` inherits `mail.thread` and `mail.activity.mixin`, which
`crm.lead` already inherits on its own, and C3 requires the most derived class
first while the base list puts it last. It went unnoticed in 18.0 because
`numa_poly` rebuilt `__bases__` by hand and undid the conflict on the way; now
that bases are *declared*, Odoo computes the order and the clash surfaces.

The link says the same thing without fighting the MRO, and it separates two
lifetimes that were never really one: a lead can exist without a workflow, and
its instance can be replaced without touching the lead.

**On the wire nothing changed.** The fields the views read —`fsm_state`,
`current_state_id`, `next_node_id`, `instance_variables`, `debug_mode`,
`json_ui_schema`— keep their names, now as related fields.

**On an upgraded database there is work to do.** Leads that were instances do
not get an `fsm_instance_id` by themselves; a running workflow has to be
migrated by hand or restarted. This module ships no migration script.

### 7.2 The negative `has_fsm` search was wrong

`has_fsm = False` used to be written as the hand-made mirror of the positive
domain. A lead with a definition but no instance has an empty `fsm_state`, and
a `not in` over the traversal does not reach it. The negative domain is now the
literal negation of the positive one.

### 7.3 The controllers are gone

`controllers/main.py` exposed four `auth='public'` routes under
`/crm_workflow/…` against the model `crm.workflow`, which does not exist in
this repository —nor does `consume_event()`, nor the template
`numa_fsm.error_on_id`, and `request.jsonrequest` was removed from Odoo years
ago. Every route raised on its first statement. The portal rendering that the
routes were reaching for is `numa_fsm`'s `/fsm/form/<instance_uuid>`, which
works against any instance, this module's included.

### 7.4 Smaller things

- `security/ir.model.access.csv` became `security/ir.access.csv`; the empty
  `security/security.xml` is gone.
- `action_assign_bot` returned `view_mode: 'tree,form'`; the view type is
  `list` since 17.0.
- `'base'` is no longer listed in `depends` —`crm` already brings it— and the
  empty `TODO` file is gone.

---

## 8. License and Author

- **Copyright:** NUMA Extreme Systems
- **License:** LGPL-3
- **Website:** [http://www.numaes.com](http://www.numaes.com)
