{
    'name': 'Asynchronous Execution Infrastructure',
    'version': '1.0',
    'author': 'Numaes',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Technical',
    'summary': 'Robust, persistent, and traceable asynchronous execution for Odoo 18.',
    'description': """
Asynchronous Execution Infrastructure
=====================================
This module provides a robust framework to execute Odoo methods in background threads using a global ThreadPoolExecutor.

Key Features:
-------------
* **Persistence:** All asynchronous tasks are saved in the database, allowing for tracking and recovery.
* **Traceability:** Integration with `numa_exceptions` for error logging.
* **Reliability:** Automatic recovery of pending jobs on server restart via post-init hook.
* **Fluent Interface:** Easy to use syntax: `recordset.asynch_exec().method_name()`.
* **Configurable:** Thread pool size configurable via Odoo configuration file.
* **Retry Mechanism:** Configurable automatic retries with delay.
    """,
    'depends': ['base', 'numa_exceptions'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
