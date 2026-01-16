# Asynchronous Execution Infrastructure (`numa_asynch_exec`)

This module provides a robust, persistent, and traceable infrastructure for executing Odoo methods asynchronously in background threads.

## Features

- **Fluent API**: Trigger asynchronous execution with a simple `.asynch_exec()` call.
- **Persistence**: Jobs are stored in the database (`numa.asynch.job`), allowing for status tracking (Pending, Running, Done, Failed).
- **Automatic Recovery**: Interrupted or pending jobs are automatically re-queued when the Odoo server starts.
- **Error Handling**: Comprehensive logging of exceptions using the `numa_exceptions` module.
- **Configurable Retries**: Support for multiple retries with configurable delays.
- **Thread Pool Management**: Uses a global `ThreadPoolExecutor` with a configurable number of worker threads.

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
recordset.asynch_exec().my_heavy_method(arg1, arg2)
```

### With Retries and Delay

You can specify the number of retries and a delay (in milliseconds):

```python
# Execute with 3 retries and 500ms delay between attempts
recordset.asynch_exec(retry=3, retry_delay=500).my_heavy_method(arg1)
```

## Technical Details

### Workflow

1. **Proxy Creation**: `asynch_exec()` returns an `AsynchProxy` object.
2. **Job Registration**: When a method is called on the proxy, it creates a `numa.asynch.job` record containing all necessary metadata (model, IDs, method name, args, kwargs, context, etc.).
3. **Post-Commit Submission**: The job is submitted to the global `ThreadPoolExecutor` only **after** the current database transaction is successfully committed. This ensures the background thread can see the job record and any data changes made in the original transaction.
4. **Execution**: The background thread:
    - Waits for the `retry_delay`.
    - Opens a new database cursor.
    - Recreates the environment (`api.Environment`) with the original user and context.
    - Executes the method.
    - Updates the job state to `done` or `failed`.
5. **Recovery**: On server startup, a `post_init_hook` triggers `_recover_pending_jobs()`, which finds any jobs still in `pending` state and re-submits them to the executor.

### Error Traceability

If an exception occurs during execution, the module performs a rollback of the background transaction and calls `register_exception` from the `numa_exceptions` module, providing full traceability of the error in the context of the asynchronous job.

---
Developed by **Numaes** - [www.numaes.com](https://www.numaes.com)
