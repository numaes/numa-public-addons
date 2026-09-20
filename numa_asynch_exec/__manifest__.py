# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
{
    'name': 'Asynchronous Execution Infrastructure',
    'version': '20.0.1.0.0',
    'author': 'Numaes',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Technical',
    'summary': 'Robust, persistent and traceable asynchronous execution for Odoo.',
    'description': """
Asynchronous Execution Infrastructure
=====================================
Runs Odoo methods in background threads, out of a process-wide thread pool,
without losing them when the request that asked for them is gone.

Key Features:
-------------
* **Persistence:** every job is a database record, so it can be followed,
  retried and read after the fact.
* **Traceability:** failures are logged through ``numa_exceptions``, with the
  stack that produced them, and the reason is kept on the job itself.
* **Recovery:** a job queued in a process that died is picked up again, by the
  recovery cron and on module install or update.
* **Fluent interface:** ``records.asynch_exec().method_name(args)``.
* **Chaining:** ``records.job_wait().first().second()`` runs the second method
  after the first; ``job_wait()`` in the middle of a chain runs the next method
  alongside the previous one.
* **Configurable:** thread pool size through ``numa_asynch_max_threads`` in the
  Odoo configuration file.
* **Retries:** a configurable number of attempts, with a delay, reusing the
  same job record.

Migrated to Odoo 20.0. See README.md for the list of API changes.
""",
    'depends': ['numa_exceptions'],
    'data': [
        'security/ir.access.csv',
        'data/numa_asynch_exec_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
