# NUMA Background Job

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). How a job is
started changed, and so did who can see one: read
[Migration to Odoo 20.0](#4-migration-to-odoo-200) before upgrading code that
uses this module.

---

## 1. Overview

**NUMA Background Job** provides a simple way to run long-running tasks in a separate thread so that the UI is not blocked. A job is created with a **model**, a **record ID**, and a **method name**. After the current transaction commits, a background thread starts and calls that method, passing the job record so the worker can report progress, complete, or abort.

Jobs are visible in the Odoo backend (list and form views). Users can monitor progress (completion rate, current status) and request abortion. Completed or aborted jobs are pruned automatically by a daily cron.

### 1.1 Key Features

| Feature | Description |
|--------|-------------|
| **Non-blocking** | Job execution runs in a daemon thread; the HTTP request returns after the job record is created. |
| **Post-commit start** | The thread is started only after the current transaction commits, so the job record exists and is committed. |
| **Progress reporting** | The worker can call `update_status(rate=..., statusMsg=...)` to update completion rate and status; changes are pushed to the UI via the bus. |
| **Abort** | Users can request abortion from the form view; the worker can check `was_aborted()` and call `end()` or `abort()` accordingly. |
| **Auto-cleanup** | A daily scheduled action deletes **finished** jobs older than the retention period (8 days by default, set with `numa_background_job.retention_days`; 0 disables it). A job still running is never deleted. |
| **Private by owner** | A job is readable only by the user who asked for it, and its progress is published to that user's bus channel alone. |

### 1.2 Dependencies

- **Odoo modules:** `bus`, `web`, `numa_exceptions`  
- **License:** LGPL-3  

---

## 2. Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | This file: overview and quick links. |
| [USER_GUIDE.md](USER_GUIDE.md) | User guide (monitoring, aborting) and developer guide (implementing worker methods, API reference, examples). |
| [CHANGES.rst](CHANGES.rst) | Version history. |

---

## 3. Quick Start (Developers)

1. **Implement a worker method** on any model with the signature `def method_name(self, bkJob):`, where `bkJob` is the `res.background_job` record. Use `bkJob.update_status(rate=..., statusMsg=...)` for progress and `bkJob.end()` or `bkJob.abort()` when done (or rely on automatic `end()` if the method returns without calling `end()` while state is still `started`).

2. **Launch a job** (e.g. from a button or another method):
   ```python
   self.env['res.background_job']._launch('Export orders', self, 'run_export')
   ```

   `_launch` is the way in. Ordinary users cannot write the job table, because
   a row in it names a method the server will call; `_launch` goes through
   `sudo()` and records the real user as the owner. It is not callable over
   RPC.

3. **Monitor** from **Settings → Technical → Background Jobs** (or the menu where the action is placed). Progress and status are updated via the bus; use **Abort** to request cancellation.

For full details, worker API, and examples, see [USER_GUIDE.md](USER_GUIDE.md).

---

## 4. Migration to Odoo 20.0

### 4.1 Jobs are started with `_launch`, not `create`

Any employee used to be able to write the job table, and a row in it names a
model and a method that the server then calls. That turned every private
method into something reachable from a browser. The table is now readable and
writable by its owner only (`[('user_id', '=', user.id)]`), with full rights
for `base.group_system`, and jobs are started through
`res.background_job._launch(name, record, method)`.

Existing code that calls `create()` directly keeps working from server code
that has the rights; from a user's session it now raises `AccessError`, and
should call `_launch` instead.

### 4.2 Progress goes to the owner, not to a public channel

Progress used to be published to the string channel `res.background_job`, and
Odoo lets a client subscribe to any string channel it asks for. Anybody with a
websocket could therefore watch everybody's jobs, including the `error` field,
which holds a full traceback. The channel is now the owner's user record, and
the notification type is `res.background_job/state`.

### 4.3 What was broken and now is not

- **The error path raised.** It passed `bkJob.args` to `register_exception`,
  and there is no `args` field: every failing job crashed while trying to log
  why it failed.
- **The worker set the wrong thread attribute:**
  `threading.current_thread().dbname` got the *job* name.
- **The retry loop re-ran jobs it had already aborted**, up to ten times,
  because `start()` only acts on a job in `init`. A failed job is not retried
  at all now: its method already had whatever effect it had.
- **A job the worker could not run stayed in `init` for ever**, because
  `abort()` refused to act on it. `abort()` and `try_to_abort()` now accept a
  job that never started, and the worker checks that its `start()` took effect
  before calling anything.
- **`refresh_state()` committed a cursor it did not own**, twice.
- **`create()` had no `@api.model_create_multi`**, so creating several jobs at
  once raised.
- **`prune()` deleted running jobs** and compared local time to UTC.
- **The Abort button was hidden exactly while the job was running**
  (`invisible="state == 'started'"`), which is the only time it means
  anything.

### 4.4 Smaller things

- The seven copies of "open a cursor, write, commit" are one `_write_status`.
  The public API (`start`, `end`, `abort`, `try_to_abort`, `update_status`,
  `was_aborted`, `get_current_state`) did not change.
- Those methods check the caller's rights: they write as superuser, on a
  cursor of their own, so the check has to be explicit.
- `security/ir.model.access.csv` became `security/ir.access.csv`; the empty
  `security/security.xml` and the empty `report/` package are gone.
- `data/autocleanup.xml` used the `<openerp>` root tag and is now
  `data/numa_background_job_data.xml`.
- `depends` no longer lists `base`.

## 5. Tests

```bash
odoo-bin -d <database> -i numa_background_job_test --without-demo --test-enable \
         --test-tags=/numa_background_job,/numa_background_job_test --stop-after-init
```

`numa_background_job/tests` covers the state transitions, the notification
channel and payload, `prune`, and the access rights. `numa_background_job_test`
runs a whole job end to end: the wizard button, the worker, a run that
finishes, one that reports an error, one that raises, one that is called off
and one whose method is not there.

The status helper writes on a cursor of its own and commits it, which is the
point of the design; the suites enter `registry_test_mode()` so that cursor
becomes a savepoint on the test's own and is rolled back with it.

---

## 6. License and Author

- **Author:** NUMA Extreme Systems  
- **Website:** [http://www.numaes.com](http://www.numaes.com)  
- **License:** LGPL-3  
