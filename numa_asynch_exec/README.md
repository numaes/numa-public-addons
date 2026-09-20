# Asynchronous Execution Infrastructure (`numa_asynch_exec`)

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). See
[Migration to Odoo 20.0](#migration-to-odoo-200) for the API changes, the
security change and the two features that used to be broken.

This module provides a robust, persistent, and traceable infrastructure for executing Odoo methods asynchronously in background threads.

## Features

- **Fluent API**: Trigger asynchronous execution with a simple `.asynch_exec()` call.
- **Chained Execution**: Use `.job_wait()` to create dependent job chains with sequential and parallel execution.
- **Persistence**: Jobs are stored in the database (`numa.asynch.job`), allowing for status tracking (Pending, Running, Done, Failed, Waiting for Dependencies).
- **Automatic Recovery**: A cron re-queues jobs that never ran, every five minutes, and the module does the same on install and update.
- **Error Handling**: Comprehensive logging of exceptions using the `numa_exceptions` module.
- **Configurable Retries**: A configurable number of attempts with a delay, reusing the same job record. A database conflict is retried on its own budget, since it means the job collided rather than failed.
- **Thread Pool Management**: Uses a global `ThreadPoolExecutor` with a configurable number of worker threads.
- **Dependency Management**: Jobs can depend on other jobs, enabling complex asynchronous workflows.
- **Visible queue**: the jobs are a list under **Settings → Technical → Database Structure → Asynchronous Jobs**, with a **Requeue** button for whatever got stuck.

## Looking at the queue

**Settings → Technical → Database Structure → Asynchronous Jobs** opens the
list, filtered on the jobs that have not finished yet; remove the filter to see
the whole history. The form shows the call as it was stored (model, ids,
arguments, context), the reason the last attempt failed, and both sides of the
dependency graph: what the job waits for, and what waits for it.

The **Requeue** button puts a job back in the queue with a fresh budget of
attempts. It is the way out for a job left in `running` by a process that died,
and for a failed job once its cause is fixed. It refuses jobs that already
finished successfully, since running them again would repeat what they did.

## Access rights

Only the system administrator (`base.group_system`) may read or write the job
tables. A row there names a model and a method that a worker thread runs **as
superuser**, so anyone able to write one could run anything. Deferring a call
does not need those rights: `asynch_exec()` and `job_wait()` create the job
through `sudo()`, so any user can use them.

## Configuration

You can configure the maximum number of worker threads in your `odoo.conf` file:

```ini
[options]
...
numa_asynch_max_threads = 5
```

If not specified, it defaults to **5** threads.

## Usage

### Basic Usage

To execute any method asynchronously, simply call `asynch_exec()` before calling the method:

```python
# Instead of:
recordset.my_heavy_method(arg1, arg2)

# Use:
job_id = recordset.asynch_exec().my_heavy_method(arg1, arg2)
```

The call returns the id of the job it created, not the result of the method:
the method has not run yet.

### With Retries and Delay

You can specify the number of retries and a delay (in milliseconds):

```python
# Execute with 3 retries and 500ms delay between attempts
recordset.asynch_exec(retry=3, retry_delay=500).my_heavy_method(arg1)
```

### Chained Execution with Dependencies

Use `job_wait()` to create chains of dependent jobs:

#### Sequential Execution

```python
# method2 runs only after method1 completes successfully
recordset.job_wait().method1().method2()
```

#### Parallel Execution

`job_wait()` in the middle of a chain runs the next method *alongside* the
previous one instead of after it. Whatever follows waits for every branch
opened since.

```python
# method1 and method2 run simultaneously, method3 runs after both complete
recordset.job_wait().method1().job_wait().method2().method3()

# three branches: method1, method2 and method3 together, then method4
recordset.job_wait().method1().job_wait().method2().job_wait().method3().method4()
```

#### Complex Chains

```python
# Multiple parallel branches, then sequential execution
recordset.job_wait().fetch_data1().job_wait().fetch_data2().process_results().send_notification()
```

#### With Retries

```python
# All jobs in the chain will retry 3 times with 500ms delay
recordset.job_wait(retry=3, retry_delay=500).validate().process().save()
```

## Technical Details

### Workflow

#### Standard Execution (`asynch_exec`)

1. **Proxy Creation**: `asynch_exec()` returns an `AsynchProxy` object.
2. **Job Registration**: When a method is called on the proxy, it creates a `numa.asynch.job` record containing all necessary metadata (model, IDs, method name, args, kwargs, context, etc.).
3. **Post-Commit Submission**: The job is submitted to the global `ThreadPoolExecutor` only **after** the current database transaction is successfully committed. This ensures the background thread can see the job record and any data changes made in the original transaction.
4. **Execution**: The background thread:
    - Waits for the `retry_delay`, before opening any cursor.
    - Opens a new database cursor.
    - Checks that the model, the records and the method are still there.
    - Claims the job with a conditional `UPDATE`, so the executor and the
      recovery cron can never both run it.
    - Executes the method **as superuser**, with the stored context. The
      requesting user stays on `uid` for audit.
    - Updates the job state to `done` or `failed`.
5. **Recovery**: The `Asynchronous jobs: recover pending` cron re-queues every
   job still in `pending` or `waiting`, every five minutes, and the module
   does the same through its `post_init_hook` on install and update.

#### Chained Execution (`job_wait`)

1. **Chain Building**: `job_wait()` returns an `AwaitProxy` object that builds a chain of dependent jobs.
2. **Job Creation**: Each method call in the chain creates a `numa.asynch.job` record.
3. **Dependency Creation**: Jobs are linked via `numa.asynch.job.dependency` records:
   - Sequential jobs: Each job depends on the previous one
   - Parallel jobs: Multiple jobs depend on the same parent(s), final job depends on all parallel jobs
4. **State Management**: Jobs with unmet dependencies are set to `waiting` state.
5. **Dependency Resolution**: When a job completes (`done`), it triggers a check of all dependent jobs:
   - If all dependencies are satisfied, the dependent job moves to `pending` and is submitted to the executor.
   - If dependencies are still pending, the job remains in `waiting` state.
6. **Execution**: Jobs execute only when all their dependencies are `done`.

### Error Traceability

If an exception occurs during execution, the module performs a rollback of the background transaction and calls `register_exception` from the `numa_exceptions` module, providing full traceability of the error in the context of the asynchronous job.

### Dependency Resolution

When using `job_wait()`, jobs with dependencies are automatically managed:

1. **Creation**: Jobs with unmet dependencies are created in `waiting` state
2. **Monitoring**: The system tracks when dependencies complete
3. **Activation**: When all dependencies are `done`, the dependent job automatically moves to `pending` and is submitted to the executor
4. **Failure Handling**: If a dependency fails, dependent jobs remain in `waiting` state (they will not execute)

### Models

#### `numa.asynch.job`

Stores asynchronous job records with all metadata needed for execution.

**Key Fields:**
- `model_name`: Target Odoo model
- `res_ids`: Record IDs to execute method on
- `method_name`: Method to call
- `args`, `kwargs`: Method arguments
- `state`: Current state (pending, running, done, failed, waiting)
- `dependency_ids`: Jobs this job depends on
- `dependent_ids`: Jobs that depend on this job
- `error`: why the last attempt failed
- `retry_count` / `concurrency_retries`: attempts spent on failures and on database conflicts

#### `numa.asynch.job.dependency`

Tracks dependency relationships between jobs.

**Key Fields:**
- `job_id`: Dependent job
- `depends_on_id`: Job that must complete first

**Validations:**
- Prevents self-dependencies
- Detects circular dependencies

---

## Examples

### Example 1: Simple Async Task

```python
# Send email without blocking
self.env['mail.mail'].asynch_exec().send()
```

### Example 2: Sequential Processing

```python
# Process order steps in sequence
order.job_wait().validate().process_payment().send_confirmation()
```

### Example 3: Parallel Data Fetching

```python
# Fetch from multiple sources simultaneously, then process
recordset.job_wait().fetch_customers().job_wait().fetch_products().merge_data()
```

### Example 4: Complex Workflow

```python
# Parallel validation, then sequential processing
recordset.job_wait().validate_rules().job_wait().check_permissions().process().notify()
```

---

## Best Practices

1. **Use `asynch_exec()` for simple, independent tasks**
2. **Use `job_wait()` for coordinated workflows**
3. **Handle errors appropriately** - check job states
4. **Avoid blocking operations** in async methods
5. **Consider transaction boundaries** - each job runs in its own transaction
6. **Monitor job states** for long-running operations
7. **Use parallel execution** to improve throughput when possible

---

## Troubleshooting

### Jobs Not Executing

- Check thread pool configuration
- Verify job records exist
- Check server logs for errors
- Ensure `numa_exceptions` module is installed

### Jobs Stuck in 'waiting'

- Check if dependency jobs completed
- Verify dependency relationships
- Check if dependencies failed. A failed dependency never releases what waits
  for it: the chain stops there, on purpose.

### Jobs Stuck in 'running'

A job whose process died while it was running stays in `running`, and the
recovery cron leaves it alone: it has no way to tell a dead worker from a job
that is simply taking a long time. Use the **Requeue** button on such a job,
once you are sure nothing is still running it.

### Circular Dependencies

- Review your `job_wait()` chain structure
- Simplify dependency relationships
- Ensure no job depends on itself

---

## Migration to Odoo 20.0

| Odoo 18.0 | Odoo 20.0 |
| --- | --- |
| `security/ir.model.access.csv` | the `ir.model.access` model is gone; ACLs and record rules are unified in `security/ir.access.csv`. A row **without a group now restricts instead of granting**, so the old group-less rows could not be carried over as they were |
| `_rec_name = 'display_name'` with a stored computed `display_name` | `display_name` is computed by the ORM; the circular definition is gone |
| `odoo.models.BaseModel` | `odoo.orm.models.BaseModel` |

Changes of behaviour that came with the migration:

- **The job tables are restricted to `base.group_system`.** They used to be
  readable and writable by every user, portal included, while a row there names
  a model and a method that a worker runs as superuser. Any authenticated user
  could therefore have arbitrary code executed with full rights.
- **`job_wait()` works.** It never did: it called `job.refresh()`, a method
  Odoo has not had for years, and nothing ever created the jobs of the root
  chain, so a chain was built and thrown away. The proxy now stores each job as
  the chain is written, which is what a fluent interface with no terminal call
  requires.
- **Recovery happens on a cron.** A `post_init_hook` runs on install and
  update, never on a restart, so the documented "recovery on server startup"
  did not exist.
- **A job cannot run twice.** The transitions into `running`, and out of
  `waiting`, are conditional `UPDATE`s. The recovery cron and the executor can
  hold the same job, and several dependencies can finish at once.
- **A retry reuses the job record** instead of copying it. An unbounded retry
  (`retry=-1`, which polling threads use) grew the table once per attempt.
- **A database conflict is not a failure.** A serialization failure or a
  deadlock means the job collided with another transaction; it is retried, with
  a backoff, on a budget of its own that does not consume `max_retries`.
- **The thread pool is built on first use**, not when the module is imported,
  so the worker count is read after Odoo has parsed its configuration.
- **The delay is waited out before a cursor is opened**, instead of holding a
  database connection for nothing.
- **`asynch_exec()` returns the job id** instead of `True`, and does not hand
  the caller a `sudo()` recordset.
- **The queue has a user interface.** The module used to have no view at all:
  the only way to see what it was doing was SQL or a shell.

Structure: the models moved to one file per model (`numa_asynch_job.py`,
`numa_asynch_job_dependency.py`, `base.py`), and the proxies, which are not
models, moved out of `models/` into `proxies.py`.

## Tests

```bash
odoo-bin -d <database> -i numa_asynch_exec --without-demo \
         --test-enable --test-tags=/numa_asynch_exec --stop-after-init
```

The suite covers the serialization helpers, the job lifecycle (what can run,
who claims it, what a failure does), the shape of the graph each chain builds,
the release of waiting jobs, cycle detection, recovery, and the access rights.
It never starts a thread: the queueing contract is asserted by capturing what
would have been submitted.

## See Also

- **User Guide**: See `USER_GUIDE.md` for detailed usage examples and best practices
- **Analysis Document**: See `numa_asynch_exec_analisis.md` for technical analysis

---
Developed by **Numaes** - [www.numaes.com](https://www.numaes.com)
