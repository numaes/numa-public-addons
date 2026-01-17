import threading
from concurrent.futures import ThreadPoolExecutor
from odoo.tools import config

# Thread-safe global executor instance
_executor_lock = threading.Lock()
max_workers = int(config.get('numa_asynch_max_threads', 5))
_executor = ThreadPoolExecutor(
    max_workers=max_workers,
    thread_name_prefix='numa_asynch_exec'
)

def get_asynch_executor():
    """
    Returns the global ThreadPoolExecutor instance, initializing it if necessary.
    The number of workers can be configured in odoo.conf via 'numa_asynch_max_threads'.
    
    :return: ThreadPoolExecutor instance
    """
    global _executor
    return _executor


from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry
try:
    from odoo.addons.numa_exceptions.models.exceptions import register_exception
except ImportError:
    def register_exception(*args, **kwargs):
        pass

import time
import logging

_logger = logging.getLogger(__name__)

def _run_in_thread(job_id, db_name, context):
    """
    Orchestrates the asynchronous execution of the job in a separate thread.
    Handles environment recreation, execution, exception logging, and retries.
    """

    registry = Registry(db_name)
    with registry.cursor() as cr:
        # Recreate environment with original user and context
        env = api.Environment(cr, SUPERUSER_ID, context or {})

        job = env['numa.asynch.job'].browse(job_id).exists()
        if not job:
            _logger.warning(f'Asynchronous job {job_id} not found, skipping execution')
            return
        # Respect configured delay before starting
        if job.retry_count > 0 and job.retry_delay > 0:
            time.sleep(job.retry_delay / 1000.0)

        # Update state to running and commit immediately to avoid re-recovery
        job.write({'state': 'running'})
        cr.commit()

        try:
            # Browse records and execute method

            user = env['res.users'].browse(job.uid).exists()
            if user:
                # impersonar al usuario que creó el job para la lógica de negocio
                # Esto garantiza que el Audit Trail registre al usuario real
                env_worker = api.Environment(cr, job.uid.id, job.context or context or {})

                recordset = env_worker[job.model_name].browse(job.res_ids).exists()
                if recordset:
                    method = getattr(recordset, job.method_name)
                    method(*job.args, **job.kwargs)

                    # Mark as successfully completed
                    _logger.debug(f'Asynchronous job {job.id} succesfully executed')
                    job.write({'state': 'done'})
                    cr.commit()
                else:
                    _logger.warning(f'Asynchronous job {job.id} no target found, skipping execution')
            else:
                _logger.warning(f'Asynchronous job {job.id} no target user found, skipping execution')

        except Exception as e:
            cr.rollback()
            # Log the exception for traceability via numa_exceptions module
            register_exception(
                f'numa_asynch_exec - job({job.id})',
                job.method_name,
                {'args': job.args, 'kwargs': job.kwargs},
                db_name,
                job.uid.id,
                e
            )

            if job.retry_count < job.max_retries:
                # Logic for automatic retry: create a copy of the job with incremented retry count
                new_job = job.sudo().copy({
                    'retry_count': job.retry_count + 1,
                    'state': 'pending',
                })
                # Mark current job as failed
                _logger.warning(
                    f'Asynchronous job {job.id} failed, retrying {new_job.retry_count}/{new_job.max_retries}')
                job.write({'state': 'failed'})

                executor = get_asynch_executor()
                # Commit failure and new job creation before re-queueing
                cr.commit()
                executor.submit(_run_in_thread, new_job.id, db_name, context)
            else:
                # Final failure if no retries left
                _logger.warning(
                    f'Asynchronous job {job.id} failed, no retry left')
                job.write({'state': 'failed'})
                cr.commit()

