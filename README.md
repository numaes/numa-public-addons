<div align="center">
  <!-- You can replace the placeholder below with your actual company logo URL -->
  <h1>Odoo 18.0 Advanced Architecture & Business Addons</h1>

  <p>
    <em>A collection of enterprise-grade, highly scalable architectural modules and business extensions for Odoo 18.0, proudly developed by <strong>NUMA EXTREME SYSTEMS</strong>.</em>
  </p>

  <p>
    <a href="https://www.numaes.com">Website</a> •
    <a href="mailto:info@numaes.com">Contact Us for Enterprise Support</a>
  </p>

  <p>
    <img alt="Odoo Version" src="https://img.shields.io/badge/Odoo-18.0-blueviolet?style=for-the-badge&logo=odoo" />
    <img alt="License" src="https://img.shields.io/badge/License-LGPL_v3-blue?style=for-the-badge" />
    <img alt="Maintained" src="https://img.shields.io/badge/Maintained%3F-Yes-green.svg?style=for-the-badge" />
  </p>
</div>

---

## 🚀 About This Repository

Welcome to the public repository of **NUMA EXTREME SYSTEMS**. We are a team of senior software engineers and architects specializing in extreme performance, infinite scalability, and complex integrations within the Odoo ecosystem.

This repository houses our public, open-source modules designed to solve hard engineering problems in Odoo 18.0. Whether you need offline-first synchronization, event-driven architectures, real-time observability, or to break Odoo's integer limits with BIGINTs, you will find foundational tools here to take your Odoo instances to the next level.

---

## 💼 Enterprise Support & Consulting

**Are you building a mission-critical system on Odoo?**

While these modules are open-source, implementing complex architectural patterns (like Pub/Sub, Offline-First Synchronization, or Asynchronous Execution) requires deep expertise.

At **NUMA EXTREME SYSTEMS**, we offer:
- **Architectural Consulting:** Design scalable, high-performance Odoo infrastructures.
- **Custom Development:** Tailor-made modules, advanced workflows, and robust integrations.
- **Enterprise Support & Maintenance:** SLA-backed support for your production environments.
- **Performance Tuning:** Optimize slow queries, manage high concurrency, and implement BIGINT scalability.

👉 **[Contact us today to discuss your project requirements: info@numaes.com](mailto:info@numaes.com)** or visit **[www.numaes.com](https://www.numaes.com)**.

---

## 📦 Module Catalog

All modules listed below are published in this repository and are currently
**✅ Available for everyone** — released as open source under the license stated
for each module, with no gated or commercial-only variants.

### Catalog at a Glance

| Module | Domain | Version | License | Status |
|---|---|---|---|---|
| [`numa_poly`](#numa_poly) | Core Architecture | 18.0.1.0.0 | AGPL-3 | ✅ Available for everyone |
| [`numa_big_id`](#numa_big_id) | Core Architecture | 18.0.1.0.0 | AGPL-3 | ✅ Available for everyone |
| [`numa_exceptions`](#numa_exceptions) | Core Architecture | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_asynch_exec`](#numa_asynch_exec) | Core Architecture | 1.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_background_job`](#numa_background_job) | Core Architecture | 18.0.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_real_time_observability`](#numa_real_time_observability) | Core Architecture | 18.0.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_fsm`](#numa_fsm) | Process Automation | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_fsm_pubsub`](#numa_fsm_pubsub) | Process Automation | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_fsm_crm`](#numa_fsm_crm) | Process Automation | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_fsm_hr`](#numa_fsm_hr) | Process Automation | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_synch`](#numa_synch) | Distributed Sync | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_synch_master`](#numa_synch_master) | Distributed Sync | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_synch_slave`](#numa_synch_slave) | Distributed Sync | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_synch_ai_assisted`](#numa_synch_ai_assisted) | Distributed Sync | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_roles`](#numa_roles) | Security | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_physical_product`](#numa_physical_product) | Product & Business | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_physical_product_sale`](#numa_physical_product-bridges) | Product & Business | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_physical_product_purchase`](#numa_physical_product-bridges) | Product & Business | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_physical_product_stock`](#numa_physical_product-bridges) | Product & Business | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_physical_product_invoice`](#numa_physical_product-bridges) | Product & Business | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_product_variant`](#numa_product_variant) | Product & Business | 18.0.0.4 | LGPL-3 | ✅ Available for everyone |
| [`numa_periodic_services`](#numa_periodic_services) | Product & Business | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_imap`](#numa_imap) | Mail & Communications | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |
| [`numa_fixed_output_mail`](#numa_fixed_output_mail) | Mail & Communications | 18.0.1.0.0 | LGPL-3 | ✅ Available for everyone |
| [`numa_poly_test`](#test--demonstration-modules) | Tests & Demos | 18.0.1.0.0 | AGPL-3 | ✅ Available for everyone |
| [`numa_background_job_test`](#test--demonstration-modules) | Tests & Demos | 18.0.0.1 | LGPL-3 | ✅ Available for everyone |

---

### 🏗️ Core Architecture & Scalability

Modules that extend or bypass standard Odoo limitations and introduce enterprise
software patterns at the framework level.

#### `numa_poly`
**True Polymorphic model inheritance for Odoo 18.0.**
Lets a single business record exist simultaneously in several models sharing one
identity (ID) and one unified ID space, replacing the JOIN-heavy `_inherits`
delegation pattern and the linear-only `_inherit` extension pattern.

- **Multiple polymorphic inheritance** through `_depend_models`, with no intermediate tables or boilerplate.
- **Shared ID space** backed by a central registry (`ir.poly_base`) for absolute referential integrity.
- **SQL-level performance**: searches and filtering across hierarchies are resolved in the database layer by patching the ORM.
- **Backward compatible**: handles pre-existing (legacy) records and ships an automatic backfill/migration engine, including a deferred cron pass for tables too large to migrate inline.
- **Dedicated web assets**: polymorphic list renderer and field widget for the backend.
- Architectural foundation of `numa_fsm`.
- ⚠️ Patches ORM internals and is therefore version-specific — see `numa_poly/doc/UPGRADE.md`.
- Status: **✅ Available for everyone** · License: AGPL-3 · Depends on: `base`, `web`

#### `numa_big_id`
**Converts every integer ID and foreign key to BIGINT (`int8`).**
Removes the ~2.1 billion record ceiling imposed by Odoo's default `int4` columns —
a hard requirement for `numa_poly`, which unifies sequences and consumes IDs faster.

- **Fully generalized pre-install hook** that migrates all integer columns of the database, with no hardcoded model or module list.
- **Automatic sequence conversion** to BIGINT.
- **Automatic handling of edge cases**: dependent views (drop and recreate), table inheritance, PostgreSQL reserved words.
- **ORM monkey patch** forcing `Integer` fields to map to BIGINT for all newly created columns.
- **Safety guard**: refuses to migrate databases above 500k records in critical tables (manual DBA migration required) and commits periodically to avoid lock exhaustion.
- ⚠️ Must be installed **before** any polymorphic module; the migration is irreversible without manual intervention.
- Status: **✅ Available for everyone** · License: AGPL-3 · Depends on: `base`

#### `numa_exceptions`
**Advanced exception logging, persistence and traceability.**
Captures, stores and lets you inspect system exceptions directly inside the Odoo
database instead of digging through server log files.

- **Persistent logging** using a separate database cursor, so the trace survives a rollback of the failing transaction.
- **Deep traceability**: full stack trace with source snippets, local variable values and per-frame method parameters.
- **Automatic capture** from Odoo's HTTP dispatcher and cron manager.
- **User-facing reference ID** delivered on error to simplify support conversations.
- **`@exception_managed` decorator** to instrument model methods with minimal code changes.
- **Retention policy** with a configurable purge (default: records older than 30 days).
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `mail`

#### `numa_asynch_exec`
**Robust, persistent and traceable asynchronous execution infrastructure.**
Runs Odoo methods on a global `ThreadPoolExecutor` while keeping every task
accountable in the database.

- **Fluent interface**: `recordset.asynch_exec().method_name()`.
- **Persistence**: every asynchronous task is stored, so it can be tracked and recovered.
- **Reliability**: pending jobs are automatically recovered on server restart via a post-init hook.
- **Configurable thread pool** size through the Odoo configuration file.
- **Retry mechanism** with configurable attempts and delay.
- **Traceability** through `numa_exceptions` integration.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `numa_exceptions`

#### `numa_background_job`
**Long-running tasks executed in background threads without blocking the UI.**
A job is declared with a model, a record id and a method; after commit, a worker
thread calls it and hands over the job record for progress reporting.

- **Backend visibility**: jobs are ordinary records users can list and monitor.
- **Live progress updates** pushed through the Odoo bus.
- **Abort support** for running jobs.
- **Developer-friendly API** documented in the module's `README.md` / `USER_GUIDE.md`.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `bus`, `web`, `numa_exceptions`

#### `numa_real_time_observability`
**Real-time observability mixin for any Odoo model, over the bus.**
Adds modern APM-style live signalling to custom models with a one-line mixin.

- **Mixin-based**: add `real_time_notify()` to any model with no schema changes.
- **Post-commit notifications only**, so observers never see uncommitted data.
- **Model-specific channels**: topics generated automatically as `observability/<model_name>`.
- **Flexible payloads**: send arbitrary custom data with each notification.
- **Defensive error handling** that never breaks the surrounding transaction.
- **Frontend and backend consumers** are both supported.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `bus`

---

### ⚙️ Process Automation — The FSM Suite

A comprehensive Finite State Machine stack for modelling, running and observing
business processes.

#### `numa_fsm`
**Visual, graph-first Finite State Machine engine for process automation.**
Design workflows as graphs of states, transitions and outcomes, and let the
engine enforce strict state control at runtime.

- **Graph-first designer**: states, transitions and outcomes modelled visually.
- **Controlled transition code** executed in a sandboxed environment (see `docs/TRANSITION_CODE_REFERENCE.md`).
- **Asynchronous event processing** on top of `numa_asynch_exec`.
- **Timers and global state** supported natively.
- **Built on `numa_poly`**, so an FSM instance can be the very business record it governs.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `mail`, `numa_poly`, `numa_asynch_exec`, `website`

#### `numa_fsm_pubsub`
**Event-driven architecture for FSM instances (Actor Model + Pub/Sub).**
Turns a monolithic, passive Odoo into a reactive system where FSM instances
communicate asynchronously and stay decoupled.

- **Actor Model**: each `fsm.instance` is an actor with identity, state and an inbox.
- **Pub/Sub topology**: actors publish to topics; subscribers are notified.
- **Schema-on-read**: the transport does not validate payloads; validation happens at reception.
- **Fully asynchronous delivery** through `numa_asynch_exec`.
- **Dynamic dispatcher** routing messages to topic-specific handlers or FSM events.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `mail`, `numa_fsm`, `numa_asynch_exec`

#### `numa_fsm_crm`
**FSM capabilities embedded into CRM leads.**
Leads become FSM instances driven by automated workflows.

- **Convert CRM leads into FSM instances** in place.
- **Assign bots** (FSM definitions) to leads for automated processing.
- **Control FSM execution directly from the lead form.**
- **Visual FSM diagram** showing the current state.
- **Step-by-step debugging** of the running workflow.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `crm`, `mail`, `numa_fsm`, `numa_poly`

#### `numa_fsm_hr`
**FSM capabilities embedded into HR employees.**
The same automation pattern as `numa_fsm_crm`, applied to employee records
(onboarding, certification, review cycles, and similar processes).

- **Convert HR employees into FSM instances.**
- **Assign bots** (FSM definitions) to employees.
- **Control FSM execution from the employee form.**
- **Visual FSM diagram** and **step-by-step debugging**.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `hr`, `mail`, `numa_fsm`, `numa_poly`

---

### 🌐 Distributed & Offline-First Synchronization

A four-module stack to keep geographically distributed or intermittently
connected Odoo nodes consistent.

#### `numa_synch`
**Foundational core of the offline-first synchronization system.**
A library layer consumed by the master and slave implementations; it is not a
runnable topology on its own.

- **Identity mapping** between local and remote IDs.
- **Synchronization rules** driven by domain filters.
- **Abstract serialization engine** shared by all node roles.
- **Documented wire protocol** in `numa_synch/PROTOCOL_SPECIFICATION.md`.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `mail`, `web`

#### `numa_synch_master`
**Turns an Odoo instance into the central server (Master).**
Exposes the endpoints slaves connect to and absorbs incoming batches safely.

- **JSON-RPC API endpoint** receiving synchronization batches.
- **Two-Phase Write strategy** (skeleton then decoration) to resolve circular dependencies.
- **Last Write Wins (LWW)** conflict resolution.
- **Namespace safety**: only explicitly allowed models are accepted.
- **Reference safety**: missing references are handled gracefully instead of aborting the batch.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `numa_synch`, `sale`, `stock`, `account`

#### `numa_synch_slave`
**Turns an Odoo instance into a branch node (Slave).**
Detects local changes, ships them to the master and reconciles the response.

- **Scheduled synchronization** through a configurable cron job.
- **Delta detection** based on `write_date`.
- **Dependency resolution** via BFS exploration of the record graph.
- **Batch processing with atomic commits.**
- **Automatic UUID generation** identifying the slave node.
- **Connection testing and manual sync trigger** from the UI.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `numa_synch`

#### `numa_synch_ai_assisted`
**AI-assisted schema adaptation for synchronizing with non-Odoo systems.**
Kicks in when standard metadata validation fails — a modified schema or a foreign
counterpart — and derives the transformation instead of failing the batch.

- **Automatic schema mapping** generated by AI.
- **Cached transformation maps** so the cost is paid once per schema pair.
- **Gap analysis logging** for fields that could not be resolved.
- **Dynamic payload transformation** applied at synchronization time.
- ⚠️ Requires the `numa_ai` module, which is **not part of this public repository**.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `numa_synch`, `numa_ai`

---

### 🔐 Security

#### `numa_roles`
**Strict RBAC (Role-Based Access Control) on top of native `res.groups`.**
Separates *Roles* from *Permissions* while remaining technically compatible with
standard Odoo groups.

- **Permissions** are atomic access units (e.g. `perm_approve_discount`) that are never assigned directly to users.
- **Roles** are collections of permissions (e.g. `role_sales_manager`) and are what users actually receive.
- **Immutable, unique technical codes** for permissions.
- **Template flag** distinguishing system-provided roles from user-created ones.
- **Enforced constraints**: permissions cannot have users, and cannot inherit from roles.
- **Conditional views and a dedicated menu structure** per record type.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `web`

---

### 📦 Product & Business Extensions

#### `numa_physical_product`
**Physical dimension management for products.**
Extends products with real-world geometry and derives the dependent magnitudes
automatically.

- **Adds width, height, length and surface** to products.
- **Automatic computation of surface and volume.**
- **Weight computed from a factor** applied to length, surface or volume, for products where weight is dimension-driven.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `product`, `stock`, `stock_account`, `purchase_stock`

#### `numa_physical_product` bridges
Four technical bridge modules propagating physical-product handling into the
standard Odoo flows. All of them are `auto_install`, so they activate on their own
as soon as both sides are present.

| Module | Purpose |
|---|---|
| `numa_physical_product_sale` | Extends sales (quotations, sale orders) with physical products. |
| `numa_physical_product_purchase` | Extends purchases with physical products. |
| `numa_physical_product_stock` | Extends inventory operations with physical products. |
| `numa_physical_product_invoice` | Extends invoicing with physical products. |

- Status: **✅ Available for everyone** · License: LGPL-3 each

#### `numa_product_variant`
**Extended product variant handling and a purchase-side configurator.**
Makes variant codes systematic and brings the sales configurator to purchasing.

- **Base code on product templates**, used to build variant codes.
- **Attribute codes** appended to the template base code to produce each variant's `default_code`.
- **Initial attributes on categories**, added automatically when a product is created.
- **Product configurator on Purchase Orders**, reusing the sales configurator to pick or create a variant from a template on a purchase order line.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `product`, `numa_physical_product`, `sale`, `purchase`

#### `numa_periodic_services`
**Administration and execution of recurring/periodic services.**
Gives operators an explicit lifecycle instead of raw cron jobs.

- **Operational lifecycle**: a service can be *configured*, *tested*, *operational* or *in maintenance*; only the operational state is scheduled.
- **Interval-based scheduling**, with a dispatcher checking every 10 minutes for services whose next run is due.
- **Execution logging** on the standard log for every run.
- **Transactional safety**: on exception, the transaction is rolled back at the next available step.
- **Configurable failure policy**: move the service to maintenance automatically on error, or retry indefinitely until a clean run.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `mail`, `numa_exceptions`

---

### ✉️ Mail & Communications

#### `numa_imap`
**IMAP behaviour extension for incoming mail servers.**

- **Leaves fetched messages as unread** on the IMAP server, so other clients still see them as new.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `fetchmail`

#### `numa_fixed_output_mail`
**Forces outgoing email to use the SMTP account as the envelope sender.**
Solves deliverability failures (SPF/DMARC) caused by sending on behalf of
arbitrary addresses.

- **SMTP user forced as sender**, while the original display name is preserved.
- **Reply-To and Return-Path guaranteed**, so replies and bounces still route correctly.
- **Per-mail-server configuration** through the outgoing mail server form.
- Status: **✅ Available for everyone** · License: LGPL-3 · Depends on: `base`, `mail`

---

### 🧪 Test & Demonstration Modules

Not intended for production databases; install them to validate an environment
or to read working examples.

| Module | Purpose | Status |
|---|---|---|
| `numa_poly_test` | Polymorphic model fixtures and the test suite exercising `numa_poly`. | ✅ Available for everyone |
| `numa_background_job_test` | Test menu and a worked usage example for `numa_background_job`. | ✅ Available for everyone |

---

## 🛠️ Installation

1. Clone this repository into your Odoo 18.0 addons path:
   ```bash
   git clone -b 18.0 https://github.com/numaes/numa-public-addons.git /path/to/your/addons/numa-public-addons
   ```
2. Update your `odoo.conf` to include the new path in `addons_path`.
3. Restart your Odoo server.
4. Enable **Developer Mode** in Odoo.
5. Go to **Apps** > **Update Apps List**.
6. Search for `Numa` and install the desired modules.

> **Ordering note:** if you plan to use `numa_poly`, install `numa_big_id` **first**,
> on an empty or small database. Its migration rewrites every integer column to
> BIGINT and is irreversible without manual database work.

---

## 🤝 Contributing & Support

We welcome contributions from the community! If you'd like to improve these modules or submit bug fixes, please open a Pull Request.

For bug reports, please use the GitHub Issues tracker.

**For production support, architectural changes, or feature additions**, please contact our core engineering team directly at [info@numaes.com](mailto:info@numaes.com) to discuss commercial arrangements.

---

## 📄 License

Modules in this repository are licensed under the **GNU LESSER GENERAL PUBLIC LICENSE, Version 3 (LGPLv3)**, except `numa_poly`, `numa_poly_test` and `numa_big_id`, which are licensed under the **GNU AFFERO GENERAL PUBLIC LICENSE, Version 3 (AGPLv3)**. Please see the [LICENSE](./LICENSE) and [COPYRIGHT](./COPYRIGHT) files for more information.

<div align="center">
  <br/>
  <b>Engineered with passion by <a href="https://www.numaes.com">NUMA EXTREME SYSTEMS</a></b>
</div>
