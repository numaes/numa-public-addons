# Numa Asynch Exec - User Guide

## Introduction

The **Numa Asynch Exec** module allows you to execute Odoo methods asynchronously in background threads. This enables long-running operations to execute without blocking the main transaction, improving user experience and system responsiveness.

**Key Benefits:**
- Non-blocking execution of heavy operations
- Automatic retry on failure
- Job persistence and recovery
- Chained execution with dependencies
- Parallel execution support

---

## Quick Start

### Installation

1. Install the module: **Apps → Search "Asynchronous Execution Infrastructure" → Install**
2. Configure thread pool size in `odoo.conf` (optional):
   ```ini
   [options]
   numa_asynch_max_threads = 5
   ```

### Basic Example

```python
# Instead of blocking execution:
self.env['res.partner'].heavy_processing_method()

# Execute asynchronously:
self.env['res.partner'].asynch_exec().heavy_processing_method()
```

---

## Using `asynch_exec()` - Simple Asynchronous Execution

### When to Use

Use `asynch_exec()` when you have a **single, independent task** that should run in the background without blocking the current transaction.

### Basic Syntax

```python
recordset.asynch_exec().method_name(arg1, arg2, kwarg1=value1)
```

### Examples

#### Example 1: Send Email Asynchronously

```python
# Send email without blocking
self.env['mail.mail'].asynch_exec().send()

# Or with retries
self.env['mail.mail'].asynch_exec(retry=3).send()
```

#### Example 2: Generate Report

```python
# Generate heavy report in background
report = self.env['report.sale.order'].asynch_exec().render_qweb_pdf(order_ids)
```

#### Example 3: Process Large Dataset

```python
# Process records without blocking
self.env['res.partner'].asynch_exec().batch_update_categories()
```

### Configuration Options

#### Retries

```python
# Retry up to 3 times on failure
recordset.asynch_exec(retry=3).method()

# Infinite retries (system threads only - use with caution!)
recordset.asynch_exec(retry=-1).poll_system_health()
```

#### Delay

```python
# Wait 500ms before execution
recordset.asynch_exec(retry_delay=500).method()

# Combine retry and delay
recordset.asynch_exec(retry=3, retry_delay=1000).method()
```

### Important Notes

- **Post-Commit Execution**: Jobs execute **after** the current transaction commits
- **Separate Transaction**: Each job runs in its own database transaction
- **User Context**: Jobs execute with the same user and context as the caller
- **No Return Values**: Methods executed asynchronously cannot return values directly

---

## Using `await()` - Chained Execution with Dependencies

### When to Use

Use `await()` when you need to:
- Execute multiple methods in sequence
- Coordinate parallel execution of independent tasks
- Build complex asynchronous workflows
- Simulate async/await programming with separate transactions

### Basic Syntax

```python
# Sequential
recordset.await().method1().method2()

# Parallel
recordset.await().method1().await().method2().method3()
```

### Sequential Execution

**Pattern:** `await().method1().method2()`

**Behavior:**
- `method1` executes first
- `method2` executes **only after** `method1` completes successfully
- If `method1` fails, `method2` will not execute

**Example:**

```python
# Process order and then send confirmation
order = self.env['sale.order'].browse(order_id)
order.await().process_payment().send_confirmation_email()
```

**Flow:**
```
1. process_payment() → Job1 (no dependencies) → Executes immediately
2. send_confirmation_email() → Job2 (depends on Job1) → Waits
3. Job1 completes → Job2 activates automatically
4. Job2 executes
```

### Parallel Execution

**Pattern:** `await().method1().await().method2().method3()`

**Behavior:**
- `method1` and `method2` execute **simultaneously**
- `method3` executes **only after both** `method1` and `method2` complete
- If either `method1` or `method2` fails, `method3` will not execute

**Example:**

```python
# Fetch data from multiple sources in parallel, then process
recordset.await().fetch_from_api1().await().fetch_from_api2().merge_results()
```

**Flow:**
```
1. fetch_from_api1() → Job1 (no dependencies) → Executes
2. fetch_from_api2() → Job2 (no dependencies) → Executes in parallel
3. merge_results() → Job3 (depends on Job1 AND Job2) → Waits
4. Both Job1 and Job2 complete → Job3 activates
5. Job3 executes
```

### Complex Chains

**Pattern:** Multiple `await()` calls create parallel branches

**Example:**

```python
# Complex workflow: parallel data fetching, sequential processing
recordset.await().fetch_customer_data().await().fetch_product_data().validate().await().check_inventory().process_order()
```

**Flow:**
```
1. fetch_customer_data() → Job1
2. fetch_product_data() → Job2 (parallel to Job1)
3. validate() → Job3 (depends on Job1 AND Job2)
4. check_inventory() → Job4 (parallel to Job3? No, depends on Job3)
5. process_order() → Job5 (depends on Job3 AND Job4)
```

**Note:** The exact dependency structure depends on how `await()` is called. Each `await()` creates a new parallel branch.

### With Retries

```python
# All jobs in the chain will retry 3 times
recordset.await(retry=3, retry_delay=500).validate().process().save()
```

**Important:** Retry configuration applies to **all jobs** in the chain.

---

## Real-World Examples

### Example 1: Order Processing Pipeline

```python
def action_confirm_order(self):
    """Confirm order with async processing"""
    self.ensure_one()
    
    # Process in background: validate → process payment → send email → update inventory
    self.await().validate_order().process_payment().send_confirmation().update_inventory()
    
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'Order Processing',
            'message': 'Your order is being processed. You will receive a confirmation email shortly.',
            'type': 'success',
        }
    }
```

### Example 2: Data Synchronization

```python
def sync_with_external_system(self):
    """Sync data with external system"""
    # Fetch from multiple sources in parallel, then sync
    self.await().fetch_customers().await().fetch_products().await().fetch_orders().sync_all()
```

### Example 3: Report Generation and Delivery

```python
def generate_and_send_report(self):
    """Generate report and send via email"""
    # Generate report, then send email (sequential)
    self.await().generate_pdf_report().send_via_email()
```

### Example 4: Validation and Notification

```python
def validate_and_notify(self):
    """Validate data and notify stakeholders"""
    # Validate in parallel, then notify
    self.await().validate_business_rules().await().check_permissions().notify_stakeholders()
```

---

## Understanding Job States

Jobs can be in one of these states:

- **Pending**: Job is ready to execute (no dependencies or all dependencies satisfied)
- **Running**: Job is currently executing
- **Done**: Job completed successfully
- **Failed**: Job failed and has no retries left
- **Waiting**: Job is waiting for dependencies to complete (new state for `await()`)

### Checking Job Status

```python
# Find jobs for a specific record
jobs = self.env['numa.asynch.job'].search([
    ('model_name', '=', 'sale.order'),
    ('res_ids', '=', [self.id])
])

# Check status
for job in jobs:
    print(f"Job {job.id}: {job.state}")
    if job.state == 'waiting':
        print(f"  Waiting for: {[dep.depends_on_id.id for dep in job.dependency_ids]}")
```

---

## Best Practices

### 1. Use `asynch_exec()` for Simple Tasks

```python
# ✅ Good: Single independent task
recordset.asynch_exec().send_email()

# ❌ Avoid: Over-engineering simple tasks
recordset.await().send_email()  # Unnecessary complexity
```

### 2. Use `await()` for Workflows

```python
# ✅ Good: Coordinated workflow
recordset.await().validate().process().save()

# ❌ Avoid: Independent tasks in chain
recordset.await().task1().task2()  # If tasks are independent, use separate asynch_exec()
```

### 3. Handle Errors Appropriately

```python
# Jobs that fail will be logged via numa_exceptions
# Check job state to determine if operation succeeded
job = self.env['numa.asynch.job'].search([
    ('model_name', '=', self._name),
    ('res_ids', '=', [self.id]),
    ('method_name', '=', 'my_method')
], limit=1, order='create_date desc')

if job and job.state == 'failed':
    # Handle failure
    pass
```

### 4. Avoid Blocking Operations in Async Methods

```python
# ✅ Good: Async method does heavy work
def heavy_processing(self):
    # Long-running operation
    time.sleep(10)
    # Process data
    pass

# ❌ Bad: Async method waits for user input
def bad_async_method(self):
    # This will block the thread!
    user_input = input("Enter value:")  # Don't do this!
```

### 5. Consider Transaction Boundaries

```python
# Remember: Each job runs in its own transaction
# Data committed in one job is visible to subsequent jobs
# But changes in the calling transaction are not visible until commit

# In your code:
self.write({'state': 'processing'})  # Not visible to async job yet
self.env.cr.commit()  # Now visible
self.asynch_exec().process()  # Can see the state change
```

---

## Common Patterns

### Pattern 1: Fire and Forget

```python
# Execute and don't wait for result
recordset.asynch_exec().log_activity()
```

### Pattern 2: Sequential Pipeline

```python
# Execute steps in order
recordset.await().step1().step2().step3()
```

### Pattern 3: Parallel Aggregation

```python
# Execute multiple tasks in parallel, then aggregate
recordset.await().task1().await().task2().aggregate()
```

### Pattern 4: Conditional Execution

```python
# Note: await() doesn't support conditional logic directly
# You need to handle this in your methods or use separate asynch_exec() calls

if condition:
    recordset.asynch_exec().method_if_true()
else:
    recordset.asynch_exec().method_if_false()
```

---

## Troubleshooting

### Jobs Not Executing

**Problem:** Jobs remain in 'pending' state

**Solutions:**
1. Check if thread pool is full (configure `numa_asynch_max_threads`)
2. Check server logs for errors
3. Verify job record exists in database
4. Check if `numa_exceptions` module is installed (for error logging)

### Jobs Stuck in 'waiting' State

**Problem:** Jobs with dependencies never execute

**Solutions:**
1. Check if dependency jobs completed successfully
2. Verify dependency relationships in `numa.asynch.job.dependency`
3. Check if dependency jobs failed (they won't trigger dependents)
4. Manually check job states:
   ```python
   job = self.env['numa.asynch.job'].browse(job_id)
   print(f"Dependencies: {job.dependency_ids.mapped('depends_on_id.state')}")
   print(f"All done: {job.all_dependencies_done}")
   ```

### Circular Dependencies

**Problem:** Error: "Circular dependency detected"

**Solution:**
- Review your `await()` chain
- Ensure jobs don't depend on themselves (directly or indirectly)
- Simplify the dependency structure

### Jobs Failing Immediately

**Problem:** Jobs fail right after creation

**Solutions:**
1. Check if method exists on the model
2. Verify method is callable (not a field)
3. Check arguments match method signature
4. Review error logs in `numa_exceptions` module
5. Verify user and recordset exist

---

## Advanced Topics

### Understanding Dependencies

Dependencies are created automatically by `await()`. You can also inspect them:

```python
# Get all jobs that depend on a specific job
job = self.env['numa.asynch.job'].browse(job_id)
dependent_jobs = job.dependent_job_ids.mapped('job_id')

# Get all jobs that a job depends on
dependencies = job.dependency_ids.mapped('depends_on_id')
```

### Manual Dependency Creation

While not recommended, you can create dependencies manually:

```python
job1 = self.env['numa.asynch.job'].create({...})
job2 = self.env['numa.asynch.job'].create({...})

# Create dependency
self.env['numa.asynch.job.dependency'].create({
    'job_id': job2.id,
    'depends_on_id': job1.id,
})
```

### Monitoring Jobs

```python
# Count jobs by state
pending = self.env['numa.asynch.job'].search_count([('state', '=', 'pending')])
running = self.env['numa.asynch.job'].search_count([('state', '=', 'running')])
waiting = self.env['numa.asynch.job'].search_count([('state', '=', 'waiting')])
done = self.env['numa.asynch.job'].search_count([('state', '=', 'done')])
failed = self.env['numa.asynch.job'].search_count([('state', '=', 'failed')])
```

---

## Limitations and Considerations

### Limitations

1. **No Return Values**: Async methods cannot return values to the caller
2. **No Timeout**: Jobs can wait indefinitely if dependencies fail
3. **No Cancellation**: Cannot cancel jobs in a chain if one fails
4. **Simple Dependencies**: Only checks if dependencies are 'done', not their results
5. **No Conditional Logic**: `await()` doesn't support if/else in the chain

### Performance Considerations

1. **Thread Pool Size**: Configure appropriately for your workload
2. **Job Volume**: Large numbers of jobs can impact database performance
3. **Dependency Chains**: Long chains may delay execution
4. **Parallel Execution**: Use parallel execution to improve throughput

### Security Considerations

1. **Method Access**: All methods can be executed asynchronously (no whitelist)
2. **User Context**: Jobs execute with the caller's user and permissions
3. **Data Access**: Jobs can access all data the user has permission to see

---

## FAQ

### Q: Can I get the result of an async method?

**A:** No, async methods execute in separate transactions and cannot return values. Use the database or other mechanisms to communicate results.

### Q: What happens if a job in a chain fails?

**A:** Dependent jobs will remain in 'waiting' state and never execute. You need to handle failures manually or implement retry logic.

### Q: Can I cancel a job?

**A:** Not directly. You would need to implement cancellation logic in your methods or manually mark jobs as failed.

### Q: How do I know when a job completes?

**A:** Check the job state:
```python
job = self.env['numa.asynch.job'].search([...], limit=1)
if job.state == 'done':
    # Job completed
    pass
```

### Q: Can I use `await()` with `asynch_exec()`?

**A:** They are separate APIs. Use `await()` for chains, `asynch_exec()` for independent tasks.

### Q: What's the difference between `await()` and `asynch_exec()`?

**A:** 
- `asynch_exec()`: Single independent job
- `await()`: Chain of dependent jobs with sequential/parallel execution

---

## Support

For questions, issues, or contributions, please contact the Numa Asynch Exec development team.

---

**Guide Version:** 1.0  
**Last Updated:** 2024
