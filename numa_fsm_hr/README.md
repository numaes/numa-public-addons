# Numa FSM HR

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). The employee no
longer *is* its FSM instance: it *has* one. That is the one change that shows
from the outside, and it is worth reading before upgrading a database:
see [Migration to Odoo 20.0](#7-migration-to-odoo-200).

---

## 1. Overview

This module drives HR employees with the FSM engine of `numa_fsm`. An employee
can be given a **bot** —an FSM definition written for HR workflows— and the
module creates and runs the workflow instance that the bot describes, with
start, pause, resume and step-by-step controls on the employee form.

It is the twin of `numa_fsm_crm`; what is said here about employees holds there
about leads.

### 1.1 Compatibility

- **Odoo version:** 20.0
- **Dependencies:** `hr`, `mail`, `numa_fsm`, `numa_poly`
- **License:** LGPL-3

---

## 2. Architecture

### 2.1 `hr.bot`

An HR bot **is** an FSM definition, through `numa_poly`:

```python
_name = 'hr.bot'
_depend_models = {'fsm.definition': 'fsm_definition_id'}
```

Creating a bot creates its `fsm.definition`; the diagram, the compiled
definition and the production state all live there. New bots get
`type = 'hr_bot'` so they can be told apart from other definitions.

### 2.2 `hr.employee`

An employee **has** an FSM instance:

```python
_name = 'hr.employee'
_inherit = ['hr.employee']

fsm_instance_id = fields.Many2one('fsm.instance', ondelete='set null')
```

| Field | Meaning |
|-------|---------|
| `bot_id` | The bot assigned to the employee. |
| `definition_id` | The FSM definition, computed from the bot but writable on its own. |
| `fsm_instance_id` | The running instance. Empty until the workflow starts. |
| `fsm_state`, `current_state_id`, `next_node_id`, `instance_variables`, `debug_mode` | Related to the instance, so the form asks the employee for them exactly as before. |
| `json_ui_schema` | Related to the **definition**: the diagram can be drawn before there is an instance. |
| `bot_state` | The human-readable label of the current node, computed from the diagram. |
| `has_fsm` | True when the employee has a definition and a running or paused instance. Searchable. |

`_ensure_fsm_instance()` is the only place an instance is created, and it
creates at most one per employee.

### 2.3 Lifecycle

1. A bot is assigned (or a definition is written directly) on an employee.
2. If the definition is in **production**, the module creates the instance and
   calls `start()` on it.
3. The instance runs, pauses at breakpoints or in step-by-step mode, and ends.
4. Deleting the instance leaves the employee intact, and the employee can be
   started again.

---

## 3. Usage

### 3.1 Creating an HR bot

1. **Employees → Configuration → HR Bots (FSM)**.
2. Create the bot and design the workflow with the diagram editor.
3. Set the state to **Production** when it is ready: only production
   definitions start by themselves.

### 3.2 Assigning a bot to an employee

Open the employee and pick a bot in the **HR Bot** field, or use the **Assign
Bot** button when there is none. The workflow starts on its own if the
definition is in production.

### 3.3 Controlling execution

The **FSM Workflow** page of the employee form appears once the employee has an
active FSM, and offers **Start FSM**, **Pause FSM** (switches the instance to
step-by-step so it stops at the next node), **Resume FSM** and **Next Step**.
It also shows the diagram with the active node highlighted and, while
debugging, the instance variables.

### 3.4 Finding employees with a workflow

The employee search view adds **With Active FSM** and **With Bot**. The first
one is `has_fsm`, which is computed *and* searchable: without a `search` method
an Odoo computed field cannot be used in a filter, and that alone invalidates
the whole search view, including the standard filters that share it.

---

## 4. Security

`security/ir.access.csv` grants `hr.bot` to employees (`base.group_user`) and to
administrators (`base.group_system`). Employee records keep the access rules of
`hr`.

---

## 5. Tests

```bash
odoo-bin -d <database> -u numa_fsm_hr --without-demo \
         --test-enable --test-tags=/numa_fsm_hr --stop-after-init
```

Eleven tests cover the compute and the search of `has_fsm` (including an
employee with a definition but no instance yet), the module's three views and
the standard ones they extend, that the employee and the instance are two
records with independent lifetimes, that the instance is created exactly once,
that the related fields read through the link, that assigning a production bot
starts the workflow, that a started workflow refuses to start twice, and that
the bots menu action opens.

### 5.1 Installing on a clean database

`numa_fsm` pulls in `website`, and `website` cannot be installed in the same run
as `numa_poly` (see the note in `numa_poly/doc/`). Install in two passes:

```bash
odoo-bin -d <db> --addons-path=<odoo>/addons -i website,hr --without-demo --stop-after-init
odoo-bin -d <db> --addons-path=<odoo>/addons,<numa-addons> -i numa_fsm_hr --without-demo --stop-after-init
```

---

## 6. Dependencies

| Module | Why |
|--------|-----|
| `hr` | The employees being driven. |
| `numa_fsm` | The FSM engine: definitions, instances, execution. |
| `numa_poly` | Polymorphic inheritance for `hr.bot`. |
| `mail` | Chatter and tracking on the bot field. |

---

## 7. Migration to Odoo 20.0

### 7.1 The employee has an instance instead of being one

Up to 18.0 the employee declared `_inherit = ['hr.employee', 'fsm.instance']`
and became the instance, with no separate record. That stopped linearising in
20.0: `fsm.instance` inherits `mail.thread` and `mail.activity.mixin`, which
`hr.employee` already inherits on its own, and C3 requires the most derived
class first while the base list puts it last. It went unnoticed in 18.0 because
`numa_poly` rebuilt `__bases__` by hand and undid the conflict on the way; now
that bases are *declared*, Odoo computes the order and the clash surfaces.

The link says the same thing without fighting the MRO, and it separates two
lifetimes that were never really one: an employee can exist without a workflow,
and their instance can be replaced without touching the employee record.

**On the wire nothing changed.** The fields the views read keep their names, now
as related fields.

**On an upgraded database there is work to do.** Employees that were instances
do not get an `fsm_instance_id` by themselves; a running workflow has to be
migrated by hand or restarted. This module ships no migration script.

### 7.2 The module did not install, and had not for two versions

Three separate faults, each enough on its own:

- The search view anchored its filters on `<filter name="my_team">`, which `hr`
  does not have. Before that it anchored on `my_employees`, which did not exist
  either: the view had been broken since at least 17.0. It now anchors on
  `message_needaction`.
- `has_fsm` was computed without a `search` method while the **With Active FSM**
  filter used it, which invalidates the whole employee search view and every
  standard view that inherits from it.
- The views read `state` after `numa_fsm` renamed it to `fsm_state`.

The negative `has_fsm` domain was also wrong: it was the hand-made mirror of the
positive one, and an employee with a definition but no instance has an empty
`fsm_state`, so a `not in` over the traversal did not reach them. It is now the
literal negation of the positive domain.

A fourth fault was not in this module: with `numa_poly` installed, **no** module
could extend a search view that had a `<searchpanel>`, and `hr`'s does. See
`numa_poly/doc/plan-2026-09-20-odoo-20-redesign.md`.

### 7.3 The controllers are gone

`controllers/main.py` was a verbatim copy of `numa_fsm_crm`'s: four
`auth='public'` routes under `/crm_workflow/…` —the CRM paths, in the HR
module— against the model `crm.workflow`, which does not exist in this
repository, calling `consume_event()`, which does not exist either, rendering an
undeclared template and reading `request.jsonrequest`, removed from Odoo years
ago. Every route raised on its first statement, and the two modules registered
the same paths. The portal rendering they reached for is `numa_fsm`'s
`/fsm/form/<instance_uuid>`, which works against any instance.

### 7.4 Smaller things

- `security/ir.model.access.csv` became `security/ir.access.csv`; the empty
  `security/security.xml` is gone.
- The bots action and `action_assign_bot` asked for the view type `tree`, which
  has been `list` since 17.0 and is not in `VIEW_TYPES` any more. Nothing
  validates `view_mode` on install, so the action loaded fine and failed when
  somebody opened the menu.
- The asset bundle pointed at `numa_fsm_hr/static/src/css/*.css`, a directory
  that does not exist.
- `'base'` is no longer listed in `depends` —`hr` already brings it— and the
  empty `TODO` file is gone.
- The bot form printed a literal `"Bot Name"`, quotes included.

---

## 8. License and Author

- **Copyright:** NUMA Extreme Systems
- **License:** LGPL-3
- **Website:** [http://www.numaes.com](http://www.numaes.com)
