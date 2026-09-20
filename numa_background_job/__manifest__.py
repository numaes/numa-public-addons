# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
{
    'name': 'NUMA Background Job',
    'version': '20.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Run a long task in a background thread, with progress the user can watch',
    'description': """
NUMA Background Job
===================

Runs a long task in a thread of its own, so the interface is not blocked while
it works.

A job names a record and a method. Once the transaction that created it
commits, a worker thread calls ``method(job)``; the method reports progress
through the job, and the user watches it move on the form through the
``bj_spinner`` widget, which is fed by the bus.

Key Features:
-------------
* **Progress that survives the job:** status is written on a cursor of its
  own, so it is visible while the job's transaction is still open and still
  there if that transaction rolls back.
* **Private by owner:** a job is readable only by the user who asked for it,
  and its progress is published to that user's bus channel alone.
* **Abortable:** the user asks, and the job stops at the next point it checks.
* **Traceable:** a failure is logged through ``numa_exceptions`` and its
  traceback is kept on the job.
* **Self-cleaning:** a daily cron deletes finished jobs after a configurable
  retention period.

Migrated to Odoo 20.0. See README.md for the list of changes.
""",
    'author': 'NUMA Extreme Systems',
    'website': 'http://www.numaes.com',
    'depends': ['bus', 'web', 'numa_exceptions'],
    'data': [
        'security/ir.access.csv',
        'views/background_job_views.xml',
        'data/numa_background_job_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            '/numa_background_job/static/src/**/*',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
