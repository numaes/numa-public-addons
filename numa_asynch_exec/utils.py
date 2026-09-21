# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""Thread pool and serialization helpers for asynchronous execution.

The worker half of the module lives here: the process-wide executor, the
conversion of call arguments into something a ``Json`` field accepts, and the
function a worker thread runs.
"""

import atexit
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from odoo import SUPERUSER_ID, api
from odoo.addons.numa_exceptions.models.exceptions import register_exception
from odoo.modules.registry import Registry
from odoo.orm.models import BaseModel
from odoo.tools import config

_logger = logging.getLogger(__name__)

# Number of worker threads; read from odoo.conf the first time the pool is used
MAX_THREADS_PARAM = 'numa_asynch_max_threads'
DEFAULT_MAX_THREADS = 5

JOB_MODEL = 'numa.asynch.job'

_executor = None
_executor_lock = threading.Lock()

# Set when the process is on its way out. A worker that has not started yet must not
# open a cursor against a registry that is being torn down: the job stays queued and the
# recovery cron picks it up on the next start. Without this, a job sitting in the pool
# when Odoo was asked to stop ran against a closed cursor and died with an error that
# looked like a bug in the job.
_shutting_down = threading.Event()


def _stop_accepting_jobs():
    """Refuse to START new jobs once the process is shutting down.

    Registered with atexit right after the pool is created, so it runs BEFORE
    ``ThreadPoolExecutor``'s own atexit hook (LIFO order), which waits for queued work.
    The jobs that are already running are left to finish.
    """
    _shutting_down.set()


def get_asynch_executor():
    """Return the process-wide thread pool, creating it on first use.

    The pool is built lazily so that importing the module neither starts
    threads nor reads the configuration before Odoo has parsed it.

    :return: the shared ``ThreadPoolExecutor``
    """
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                max_workers = int(config.get(MAX_THREADS_PARAM, DEFAULT_MAX_THREADS))
                _executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix='numa_asynch_exec',
                )
                atexit.register(_stop_accepting_jobs)
                _logger.info("Asynchronous executor started with %d workers", max_workers)
    return _executor


def make_json_serializable(data):
    """Render call arguments as something a ``Json`` field accepts.

    Dates become ISO strings and recordsets become their list of ids; the
    worker rebuilds the recordset from the model name stored on the job.

    :param data: any argument, container or recordset
    :return: a JSON-serializable equivalent
    """
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    if isinstance(data, BaseModel):
        return data.ids
    if isinstance(data, dict):
        return {str(key): make_json_serializable(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [make_json_serializable(value) for value in data]
    return data


def submit_job(job_id, db_name, context, delay=0):
    """Queue a job on the executor.

    :param job_id: id of the ``numa.asynch.job`` record
    :param db_name: database the job belongs to
    :param context: context to rebuild the worker environment with
    :param delay: milliseconds to wait before running the job
    """
    get_asynch_executor().submit(run_job, job_id, db_name, context, delay)


def run_job(job_id, db_name, context, delay=0):
    """Run one job in a worker thread.

    Opens its own cursor, claims the job, calls the method and records the
    outcome. Never raises: a worker thread has nobody to raise to.

    :param job_id: id of the ``numa.asynch.job`` record
    :param db_name: database the job belongs to
    :param context: context to rebuild the worker environment with
    :param delay: milliseconds to wait before running the job
    """
    try:
        _run_job(job_id, db_name, context, delay)
    except Exception:  # noqa: BLE001 - nothing above a worker thread catches this
        _logger.exception("Unhandled error running asynchronous job %s on %s", job_id, db_name)


def _run_job(job_id, db_name, context, delay=0):
    if _shutting_down.is_set():
        _logger.info(
            "Asynchronous job %s not started: the process is shutting down. It stays "
            "queued and the recovery cron will run it.", job_id)
        return

    threading.current_thread().dbname = db_name

    # The delay is honoured before a cursor is opened: sleeping with a cursor
    # in hand holds a database connection for nothing.
    if delay > 0:
        time.sleep(delay / 1000.0)

    registry = Registry(db_name)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, context or {})
        job = env[JOB_MODEL].browse(job_id).exists()
        if not job:
            _logger.warning("Asynchronous job %s not found, skipping execution", job_id)
            return

        problem = job._check_runnable()
        if problem:
            _logger.error("Asynchronous job %s cannot run: %s", job.id, problem)
            job.write({'state': 'failed', 'error': problem})
            cr.commit()
            return

        if not job._all_dependencies_done():
            job.write({'state': 'waiting'})
            cr.commit()
            return

        if not job._claim():
            # Another worker got there first; the recovery cron and the
            # executor can both hold the same job.
            _logger.debug("Asynchronous job %s already claimed, skipping", job.id)
            return
        cr.commit()

        try:
            job._execute()
            job.write({'state': 'done', 'error': False})
            cr.commit()
            job._trigger_dependents()
        except Exception as error:  # noqa: BLE001 - the outcome is recorded, not raised
            cr.rollback()
            register_exception(
                'numa_asynch_exec - job(%s)' % job.id,
                job.method_name,
                {'args': job.args, 'kwargs': job.kwargs},
                db_name,
                job.uid.id if job.uid else None,
                error,
            )
            job._record_failure(error)
            retrying, delay = job.state == 'pending', job._next_delay()
            cr.commit()
            if retrying:
                submit_job(job.id, db_name, context, delay)
