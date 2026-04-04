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
from datetime import date, datetime
from odoo.models import BaseModel

_logger = logging.getLogger(__name__)

def make_json_serializable(data):
    """
    Recursively processes data to make it JSON serializable.
    Converts:
    - datetime/date objects to ISO format strings.
    - Recordsets to lists of IDs.
    - Other non-serializable objects to their string representation.
    """
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    elif isinstance(data, BaseModel):
        return data.ids
    elif isinstance(data, dict):
        return {k: make_json_serializable(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [make_json_serializable(v) for v in data]
    return data

def _run_in_thread(job_id, db_name, context):
    """
    Orchestrates the asynchronous execution of the job in a separate thread.
    Handles environment recreation, execution, exception logging, and retries.
    
    Supports infinite retries when max_retries < 0 (system threads only).
    """

    registry = Registry(db_name)
    with registry.cursor() as cr:
        # Recreate environment with original user and context
        env = api.Environment(cr, SUPERUSER_ID, context or {})

        job = env['numa.asynch.job'].browse(job_id).exists()
        if not job:
            _logger.warning(f'Asynchronous job {job_id} not found, skipping execution')
            return
        
        # Validate user exists before proceeding
        if not job.uid:
            _logger.error(f'Asynchronous job {job.id} has no user assigned, marking as failed')
            job.write({'state': 'failed'})
            cr.commit()
            return
            
        user = env['res.users'].browse(job.uid.id).exists()
        if not user:
            _logger.error(f'Asynchronous job {job.id} user {job.uid.id} not found, marking as failed')
            job.write({'state': 'failed'})
            cr.commit()
            return

        # Validate recordset exists before proceeding
        env_worker = api.Environment(cr, job.uid.id, job.context or context or {})
        recordset = env_worker[job.model_name].browse(job.res_ids).exists()
        if not recordset:
            _logger.error(f'Asynchronous job {job.id} no target records found (model: {job.model_name}, ids: {job.res_ids}), marking as failed')
            job.write({'state': 'failed'})
            cr.commit()
            return

        # Validate method exists and is callable before proceeding
        if not hasattr(recordset, job.method_name):
            _logger.error(f'Asynchronous job {job.id} method "{job.method_name}" does not exist on model "{job.model_name}", marking as failed')
            job.write({'state': 'failed'})
            cr.commit()
            return
            
        method = getattr(recordset, job.method_name)
        if not callable(method):
            _logger.error(f'Asynchronous job {job.id} "{job.method_name}" is not a callable method on model "{job.model_name}", marking as failed')
            job.write({'state': 'failed'})
            cr.commit()
            return

        # Check dependencies before execution
        if job.has_dependencies:
            if not job.all_dependencies_done:
                # Still waiting for dependencies
                if job.state != 'waiting':
                    job.write({'state': 'waiting'})
                    cr.commit()
                return
            # All dependencies done, can proceed

        # Apply configured delay if set (for initial execution or retries)
        if job.retry_delay > 0:
            time.sleep(job.retry_delay / 1000.0)

        # Update state to running and commit immediately to avoid re-recovery
        # Only after all validations passed
        job.write({'state': 'running'})
        cr.commit()

        try:
            # Execute the method (Json fields return False when NULL — normalise)
            _args = job.args if isinstance(job.args, (list, tuple)) else []
            _kwargs = job.kwargs if isinstance(job.kwargs, dict) else {}
            method(*_args, **_kwargs)

            # Mark as successfully completed
            _logger.debug(f'Asynchronous job {job.id} successfully executed')
            job.write({'state': 'done'})
            cr.commit()
            
            # Check and trigger dependent jobs
            job._check_and_trigger_dependents()

        except Exception as e:
            cr.rollback()
            # Log the exception for traceability via numa_exceptions module
            uid_for_logging = job.uid.id if job.uid else None
            register_exception(
                f'numa_asynch_exec - job({job.id})',
                job.method_name,
                {'args': job.args, 'kwargs': job.kwargs},
                db_name,
                uid_for_logging,
                e
            )

            # Check if we should retry (infinite retries if max_retries < 0)
            should_retry = False
            if job.max_retries < 0:
                # Infinite retries (system threads only)
                should_retry = True
                _logger.warning(
                    f'Asynchronous job {job.id} failed, retrying (infinite retries mode, attempt {job.retry_count + 1})')
            elif job.retry_count < job.max_retries:
                # Finite retries
                should_retry = True
                _logger.warning(
                    f'Asynchronous job {job.id} failed, retrying {job.retry_count + 1}/{job.max_retries}')

            if should_retry:
                # Logic for automatic retry: create a copy of the job with incremented retry count
                new_job = job.sudo().copy({
                    'retry_count': job.retry_count + 1,
                    'state': 'pending',
                })
                # Mark current job as failed (for tracking)
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

