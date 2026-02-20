# NUMA Background Job

**Odoo 18.0** | LGPL-3 | NUMA Extreme Systems

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
| **Auto-cleanup** | A scheduled action runs daily and deletes old jobs (initialized more than 8 days ago). |

### 1.2 Dependencies

- **Odoo modules:** `base`, `bus`, `web`, `numa_exceptions`  
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

2. **Create a job** (e.g. from a button or another method):
   ```python
   self.env['res.background_job'].create({
       'name': 'Export orders',
       'model': self._name,
       'res_id': self.id,
       'method': 'run_export',
   })
   ```

3. **Monitor** from **Settings → Technical → Background Jobs** (or the menu where the action is placed). Progress and status are updated via the bus; use **Abort** to request cancellation.

For full details, worker API, and examples, see [USER_GUIDE.md](USER_GUIDE.md).

---

## 4. License and Author

- **Author:** NUMA Extreme Systems  
- **Website:** [http://www.numaes.com](http://www.numaes.com)  
- **License:** LGPL-3  
