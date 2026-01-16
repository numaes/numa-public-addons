# NUMA Exceptions

This module provides a robust infrastructure for capturing, persisting, and analyzing system exceptions directly within the Odoo database. It is designed to facilitate debugging and system administration by providing detailed error reports without requiring direct access to server logs.

## Features

- **Persistent Logging:** Exception information is stored in the database, ensuring that error details are not lost after server restarts.
- **Detailed Traceability:** For every exception, the module records:
    - Complete stack trace.
    - Source code snippets around the error line.
    - Values of local variables for each frame.
    - Method parameters and the service involved.
- **Automatic Capture:**
    - **HTTP Dispatcher:** Automatically intercepts unhandled exceptions in web requests.
    - **Cron Manager:** Automatically logs failures in scheduled actions (Crons).
- **User Assistance:** When a non-standard error occurs, the user is presented with a friendly message containing a unique **Exception Reference ID** (e.g., `EXC/2026/0001`). This ID can be sent to support for quick identification of the problem.
- **Retention Policy:** To prevent excessive database growth, a scheduled action automatically purges records older than 30 days, unless they are explicitly marked as "Do not purge".
- **Automatic Decorator:** Easy integration via the `@exception_managed` decorator to automatically log exceptions in any model method.

## Technical Overview

The core of the module is the `register_exception` utility function. To ensure reliability, this function:
1. Opens a **new database cursor**.
2. Creates the exception record in a **separate transaction**.
3. Commits the new cursor immediately.

This approach guarantees that even if the main transaction that caused the error is rolled back, the exception log itself is successfully saved to the database.

## Usage for Developers

While the module captures most errors automatically, you can manually log exceptions using the `@exception_managed` decorator, the `register_exception` function, or the `new_exception` method on `base.general_exception`.

### Decorator Usage (Recommended)

The easiest way to log exceptions is to use the `@exception_managed` decorator. This will automatically capture the context, database, user, and any exceptions raised during the execution of the method.

```python
from odoo.addons.numa_exceptions.models.exceptions import exception_managed

class MyModel(models.Model):
    _name = 'my.model'

    @api.model
    @exception_managed(service_name="External Integration")
    def process_data(self, data):
        # Any exception raised here will be automatically logged to numa_exceptions
        # and then re-raised to maintain normal Odoo behavior.
        return self._do_heavy_lifting(data)
```

### Manual Registration

```python
from odoo.addons.numa_exceptions.models.exceptions import register_exception

try:
    # Your complex logic here
    result = 1 / 0
except Exception as e:
    register_exception(
        service_name='my_module.my_service',
        method='calculate_value',
        params={'input': 10},
        db=self.env.cr.dbname,
        uid=self.env.uid,
        e=e
    )
    # Optionally re-raise or handle the exception
    raise
```

## Data Retention

Exception logs can be found under the **Settings > Technical > Exceptions > Exception Logs** menu.
The scheduled action **"Exceptions: Purge old logs"** runs periodically to clean up the database. You can adjust the frequency or disable it as needed.

---
**Developed by:** NUMA Extreme Systems  
**Website:** [www.numaes.com](https://www.numaes.com)  
**License:** LGPL-3
