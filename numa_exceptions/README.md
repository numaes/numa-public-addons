# NUMA Exceptions

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). See
[Migration to Odoo 20.0](#migration-to-odoo-200) for what changed and what it
means for code that depends on this module.

This module provides a robust infrastructure for capturing, persisting, and analyzing system exceptions directly within the Odoo database. It is designed to facilitate debugging and system administration by providing detailed error reports without requiring direct access to server logs.

## Features

- **Persistent Logging:** Exception information is stored in the database, ensuring that error details are not lost after server restarts.
- **Detailed Traceability:** For every exception, the module records:
    - Complete stack trace.
    - Source code snippets around the error line.
    - Values of local variables for each frame.
    - Method parameters and the service involved.
- **Automatic Capture:**
    - **Requests:** `ir.http._handle_error` is extended, which covers every dispatcher
      (HTTP, JSON-RPC and JSON2) in a single place.
    - **Cron Manager:** `ir.cron._callback` is extended, so failures in scheduled
      actions are logged.
- **User Assistance:** When a non-standard error occurs, the user is presented with a friendly message containing a unique **Exception Reference ID** (e.g., `EXC/2026/0001`). This ID can be sent to support for quick identification of the problem.
- **Retention Policy:** To prevent excessive database growth, a daily scheduled action
  purges records older than the retention period, unless they are explicitly marked as
  "Do not purge". The period defaults to 30 days and is set with the
  `numa_exceptions.retention_days` system parameter; `0` disables the purge.
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

Exception logs are found under **Settings > Technical > Database Structure > Exceptions**,
and are visible to the system administrator (`base.group_system`) only: a stack frame
carries the local variables of every method it crossed.

The scheduled action **"Exceptions cleaning"** runs daily. Two ways to change what it
keeps:

- `numa_exceptions.retention_days` system parameter: number of days to keep, `0` to
  disable the purge. It defaults to 30 when the parameter is absent.
- The `Do not purge` flag on an individual log, which the purge always respects.

## Migration to Odoo 20.0

Odoo 20.0 removed or moved most of the APIs this module was built on. What changed:

| Odoo 18.0 | Odoo 20.0 |
| --- | --- |
| `from odoo.osv import expression` | the `odoo.osv` package is gone; domains are combined with `odoo.fields.Domain` |
| `_name_search()` | replaced by `_search_display_name(operator, value)` |
| `security/ir.model.access.csv` | the `ir.model.access` model is gone; ACLs and record rules are unified in `security/ir.access.csv` |
| `odoo.http.HttpDispatcher`, `JsonRPCDispatcher`, `Dispatcher`, `SessionExpiredException` | `odoo.http` no longer re-exports them; they live in `odoo.http.dispatcher` and `odoo.http.session` |
| `ir.cron._handle_callback_exception()` | removed; the extension point is `ir.cron._callback()` |
| `from odoo import registry` | `from odoo.modules.registry import Registry` |
| `_("...")` | `self.env._("...")` |

Changes of behaviour that came with the migration:

- **Request exceptions are logged once.** Odoo 18.0 patched the three dispatcher
  classes *and* overrode `ir.http._dispatch`, which registered the same exception
  twice. Odoo 20.0 funnels every dispatcher through `ir.http._handle_error`, so a
  single override replaces all four hooks and also covers the new `Json2Dispatcher`.
- **Access is restricted to `base.group_system`.** The logs used to be readable and
  deletable by any employee, while they contain the local variables of arbitrary
  methods.
- **Captured source code is HTML-escaped** before being stored, so a source line
  containing `<` renders as written.
- **The retention period is configurable**, as the documentation already claimed.
- **Parameters are always truncated** to 10.000 characters; the 18.0 code only
  truncated them for values that were neither `dict` nor `list`.
- **An exception without a traceback is still logged**, with an empty stack, instead
  of being silently dropped.
- **A stack deeper than 100 frames keeps its innermost frames.** The 18.0 code
  stopped the walk after 100 frames from the top, so a deep recursion lost exactly
  the frames that said where it broke.
- **`new_exception` returns the reference** it registered, instead of `None`.

Structure: `models/exceptions.py` keeps the public helpers (`register_exception`,
`exception_managed`, and the pure capture functions), so the import paths documented
above are unchanged. The models themselves moved to one file per model
(`base_general_exception.py`, `base_frame.py`, `base_variable_value.py`, `ir_http.py`,
`ir_cron.py`), which is the Odoo house rule.

## Tests

```bash
odoo-bin -d <database> -i numa_exceptions --without-demo=all \
         --test-enable --stop-after-init
```

`tests/test_capture.py` covers the capture helpers, which need no cursor: filtering of
sensitive locals, truncation, HTML escaping, frame ordering and bounding, the
`__cause__` chain, parameter serialization, and the guards that make
`register_exception` unable to raise. `tests/test_exception_log.py` covers the models:
reference sequence, `frames_count`, cascade deletion, the purge and its parameter, the
frame search, and the access rights.

---
**Developed by:** NUMA Extreme Systems  
**Website:** [www.numaes.com](https://www.numaes.com)  
**License:** LGPL-3
