# NUMA Background Job — User and Developer Guide

This guide explains how to use background jobs from the UI (monitoring, aborting) and how to implement and trigger them as a developer. All content is in professional English.

---

## Table of Contents

1. [User Guide: Monitoring and Managing Jobs](#1-user-guide-monitoring-and-managing-jobs)
2. [Developer Guide: Implementing Background Jobs](#2-developer-guide-implementing-background-jobs)
3. [API Reference](#3-api-reference)
4. [Examples](#4-examples)
5. [Best Practices and Troubleshooting](#5-best-practices-and-troubleshooting)

---

## 1. User Guide: Monitoring and Managing Jobs

### 1.1 Where to Find Background Jobs

Open the **Background Jobs** menu (typically under **Settings → Technical** or a custom parent such as **Background Jobs**). You will see a list of jobs with:

- **Name** — Label given when the job was created  
- **Model / Resource ID / Method** — Which record and method are running  
- **Completion rate** — Percentage (0–100)  
- **Current status** — Short message set by the worker  
- **State** — Initializing, Started, Ended, Aborting…, Aborted  
- **Dates** — Initialized on, Started on, Ended on, Aborted on  

Use the list filters to show only Initialized, Started, Ended, or Aborted jobs. Open a record to see the form view with full details and the **Abort** button when the job is running.

### 1.2 Job States

| State | Meaning |
|-------|--------|
| **Initializing** | Job record has been created; the background thread has not yet started (e.g. waiting for transaction commit). |
| **Started** | The worker method is running. Progress and status can change. |
| **Ended** | The job finished normally (worker called `end()` or the framework ended it when the method returned). |
| **Aborting …** | The user (or system) requested abortion; the worker should check `was_aborted()` and stop. |
| **Aborted** | The job was aborted (error or user abort). The **Error** field may contain a message or traceback. |

### 1.3 Monitoring Progress

- **Completion rate** and **Current status** are updated by the worker during execution. The UI is notified via the Odoo bus, so you may see updates without refreshing (depending on your front-end integration).
- **Error** shows the last error message or traceback if the job ended in error or was aborted due to an exception.

### 1.4 Aborting a Job

- Open the job form view. If the state is **Started**, an **Abort** button is available.
- Click **Abort**. The job state is set to **Aborted** (or **Aborting …** depending on configuration). The worker runs in a separate thread; it should periodically check `was_aborted()` and exit. Once the user has requested abort, no further progress updates from the worker are required.
- Aborted jobs are not restarted. They are removed by the automatic cleanup after several days.

### 1.5 Automatic Cleanup

Completed and aborted jobs are pruned automatically by a scheduled action that runs daily. Jobs whose **Initialized on** date is older than 8 days are deleted. No manual cleanup is required.

---

## 2. Developer Guide: Implementing Background Jobs

### 2.1 How Jobs Are Executed

1. Your code creates a `res.background_job` record with `name`, `model`, `res_id`, and `method`.
2. When the **current transaction commits**, a post-commit hook starts a **daemon thread**.
3. The thread opens a new database cursor and runs with **SUPERUSER_ID** and the same context (with a default language if missing).
4. The framework calls `job.start()`, then resolves `env[model].browse(res_id)` and calls `method(bkJob)` on that record.
5. The worker method receives the **background job record** (`bkJob`) as the only argument (besides `self`). It should use `bkJob` to update progress, end, or abort.
6. When the method returns, if the job state is still `started`, the framework calls `bkJob.end()`. If the method raises an exception, the job is aborted and the traceback is stored in `error`.
7. State and progress are pushed to the bus so the UI can refresh.

### 2.2 Worker Method Signature

Implement a method on the **model** that will run the task (the model and record identified by `res_id`). The method must accept the background job record as the second argument:

```python
def my_background_method(self, bkJob):
    # self = current record (e.g. sale.order)
    # bkJob = res.background_job record
    pass
```

The method is invoked on a **single record**: `env[model].browse(res_id).my_background_method(bkJob)`.

### 2.3 What the Worker Can Do with `bkJob`

- **Update progress:** `bkJob.update_status(rate=50, statusMsg='Processing batch 2/4')`  
- **Finish successfully:** `bkJob.end(statusMsg='Done')`  
- **Abort:** `bkJob.abort(statusMsg='Cancelled', errorMsg='...')`  
- **Check if user requested abort:** `if bkJob.was_aborted(): return`  
- **Read state:** `state, rate = bkJob.get_current_state()`  

Progress and status are written to the database and broadcast via the bus so the UI can show them. See [§3 API Reference](#3-api-reference) for full method details.

### 2.4 Creating a Job from Code

Create a job only when you are ready to run it; the thread starts after the **current transaction commits**. Example:

```python
def action_long_export(self):
    self.ensure_one()
    self.env['res.background_job'].create({
        'name': f'Export {self.name}',
        'model': self._name,
        'res_id': self.id,
        'method': 'run_export',
    })
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': _('Export started'),
            'message': _('The export is running in the background. Check Background Jobs for progress.'),
            'type': 'info',
            'sticky': False,
        },
    }
```

Do not depend on the job having already started before the create() returns; the thread starts after commit.

### 2.5 Transaction and Cursor Behaviour

- The **worker** runs in a **separate thread** with a **new cursor**. It must commit or rollback its own work. The framework commits after `start()`, after `end()` / `abort()`, and after `update_status()` (via the method’s internal commit and bus send).
- The worker can perform multiple operations and commits in a single run. If the method returns without calling `end()` or `abort()`, and the state is still `started`, the framework calls `end()` when the method returns.
- If the worker raises an exception, the framework rolls back the worker’s cursor and calls `abort()` with the traceback.

---

## 3. API Reference

### 3.1 Model: `res.background_job`

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char | Job label. |
| `model` | Char | Technical name of the model (e.g. `sale.order`). |
| `res_id` | Integer | ID of the record on which the method is called. |
| `method` | Char | Name of the method to call (e.g. `run_export`). |
| `reference_id` | Integer | Optional reference (e.g. for linking to another record). |
| `state` | Selection | `init`, `started`, `ended`, `aborting`, `aborted`. |
| `completion_rate` | Integer | 0–100. |
| `current_status` | Text | Short status message. |
| `error` | Text | Last error message or traceback. |
| `initialized_on` / `started_on` / `ended_on` / `aborted_on` | Datetime | Timestamps. |

### 3.2 Methods on the Job Record (for use inside the worker or from outside)

| Method | Description |
|--------|-------------|
| `bkJob.start(statusMsg=None)` | Called by the framework when the thread starts. Marks the job as `started`. |
| `bkJob.end(statusMsg=None, errorMsg=None)` | Sets state to `ended`, sets optional status/error, and notifies the UI. |
| `bkJob.abort(statusMsg=None, errorMsg=None)` | Sets state to `aborted`, sets optional status/error, and notifies the UI. |
| `bkJob.try_to_abort(statusMsg=None)` | Sets state to `aborting` (used when the user requests abort). The worker should call `was_aborted()` and then `abort()` or `end()`. |
| `bkJob.was_aborted()` | Returns `True` if the job is no longer in state `started` (e.g. user requested abort). The worker should check this in long loops and exit. |
| `bkJob.update_status(rate=None, statusMsg=None, errorMsg=None)` | Updates `completion_rate`, `current_status`, and optionally `error` for a job in state `started`, then notifies the UI. |
| `bkJob.get_current_state()` | Returns `(state, completion_rate)`. Useful for the worker to inspect current state. |
| `bkJob.refresh_state()` | Pushes current state to the bus (normally called internally). |
| `prune()` (model method) | Deletes jobs initialized more than 8 days ago. Called by the daily cron. |

### 3.3 Creating a Job

- **API:** `env['res.background_job'].create({'name': ..., 'model': ..., 'res_id': ..., 'method': ...})`.
- **Effect:** A record is created; after the current transaction commits, a daemon thread starts and runs the given method on the given record, passing the job record.

---

## 4. Examples

### 4.1 Simple Export (single transaction)

```python
def run_export(self, bkJob):
    self.ensure_one()
    # Do work...
    data = self._generate_export_data()
    self._write_export_attachment(data)
    bkJob.update_status(rate=100, statusMsg='Export ready')
    bkJob.end(statusMsg='Completed')
```

### 4.2 Long Task with Progress and Abort Check

```python
def run_batch_import(self, bkJob):
    self.ensure_one()
    lines = self.env['import.line'].search([('batch_id', '=', self.id)])
    total = len(lines)
    for i, line in enumerate(lines):
        if bkJob.was_aborted():
            bkJob.abort(statusMsg='Cancelled by user')
            return
        line.process()
        rate = int((i + 1) / total * 100) if total else 100
        bkJob.update_status(rate=rate, statusMsg=f'Processed {i + 1}/{total}')
    bkJob.end(statusMsg='Import completed')
```

### 4.3 Job Creation from a Button

```python
def action_generate_report(self):
    self.ensure_one()
    self.env['res.background_job'].create({
        'name': f'Report: {self.name}',
        'model': self._name,
        'res_id': self.id,
        'method': 'run_generate_report',
    })
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': _('Report generation started'),
            'message': _('Check Background Jobs for progress.'),
            'type': 'info',
        },
    }

def run_generate_report(self, bkJob):
    self.ensure_one()
    try:
        report = self._build_report()
        self._attach_report(report)
        bkJob.end(statusMsg='Report generated')
    except Exception as e:
        bkJob.abort(statusMsg='Failed', errorMsg=str(e))
```

### 4.4 Multiple Commits in One Run

The worker can commit several times (e.g. to persist partial results). It still must call `end()` or `abort()` when finished, or the framework will call `end()` when the method returns.

```python
def run_long_sync(self, bkJob):
    self.ensure_one()
    for page in range(10):
        if bkJob.was_aborted():
            bkJob.abort(statusMsg='Stopped by user')
            return
        self._sync_page(page)
        self.env.cr.commit()
        bkJob.update_status(rate=(page + 1) * 10, statusMsg=f'Page {page + 1}/10')
    bkJob.end(statusMsg='Sync completed')
```

---

## 5. Best Practices and Troubleshooting

### 5.1 Best Practices

- **Name jobs clearly** so users can identify them in the list (e.g. include record name or ID).
- **Update progress** in long-running workers with `update_status(rate=..., statusMsg=...)` so users see activity.
- **Check `was_aborted()`** in loops and long operations so the job can stop when the user clicks Abort.
- **Call `end()` or `abort()`** explicitly when the worker finishes (or let the framework call `end()` on return). Set a final `statusMsg` and, for failures, `errorMsg`.
- **Avoid heavy work in the request** that creates the job; only create the record and return. All work should happen in the worker method.
- **Handle exceptions** inside the worker where possible; unhandled exceptions are caught by the framework and the job is aborted with the traceback in `error`.

### 5.2 Troubleshooting

| Issue | What to check |
|-------|----------------|
| Job never leaves "Initializing" | Ensure the transaction that created the job commits (e.g. no later rollback). The thread starts in a post-commit hook. |
| "No method defined!" | The `method` name must match a method on the model; the record `res_id` must exist. |
| Job stays "Started" after method returns | The framework calls `end()` when the method returns if state is still `started`. If it does not, check for uncommitted rollback or another process changing state. |
| Abort not taking effect | The worker must call `was_aborted()` and exit (and call `abort()` or `end()`). If the worker does not check, it will run to completion. |
| UI not updating | Progress is sent via the bus channel `res.background_job`. Ensure the front end subscribes to that channel if you need live updates. |
| Old jobs not deleted | The cron "AutoVacuum background jobs objects" runs daily and prunes jobs older than 8 days. Ensure the cron is active. |

### 5.3 Dependencies

- **numa_exceptions:** Used to register exceptions when a job fails; if the module is not installed, exception registration is skipped and the job is still aborted with the traceback stored in `error`.

---

**Module:** numa_background_job · **Version:** 18.0  
**See also:** [README.md](README.md), [CHANGES.rst](CHANGES.rst)
