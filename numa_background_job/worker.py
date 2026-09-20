# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The thread a background job runs in."""

import logging
import threading
import traceback

from odoo import api
from odoo.addons.numa_exceptions.models.exceptions import register_exception
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

JOB_MODEL = 'res.background_job'


def start_worker(db_name, uid, job_name, job_id, context=None):
    """Run a job in a thread of its own.

    :param db_name: database the job belongs to
    :param uid: user the method runs as, the one who asked for the job
    :param job_name: the job's name, for the logs
    :param job_id: id of the ``res.background_job`` record
    :param context: context to rebuild the worker environment with
    """
    threading.Thread(
        target=run_job,
        args=(db_name, uid, job_name, job_id, context),
        name='numa_background_job-%s' % job_id,
        daemon=True,
    ).start()


def run_job(db_name, uid, job_name, job_id, context=None):
    """Run one background job. Never raises: a worker thread has nobody to raise to."""
    try:
        _run_job(db_name, uid, job_name, job_id, context)
    except Exception:  # noqa: BLE001 - nothing above a worker thread catches this
        _logger.exception("Unhandled error running background job %s (%s)", job_id, job_name)


def _run_job(db_name, uid, job_name, job_id, context=None):
    threading.current_thread().dbname = db_name
    context = dict(context or {})
    context.setdefault('lang', 'en_US')

    registry = Registry(db_name)
    with registry.cursor() as cr:
        env = api.Environment(cr, uid, context)
        job = env[JOB_MODEL].browse(job_id).exists()
        if not job:
            _logger.error("Background job %s (%s) no longer exists", job_id, job_name)
            return

        problem = job._check_runnable()
        if problem:
            _logger.error("Background job %s (%s) cannot run: %s", job_id, job_name, problem)
            job.abort(statusMsg=env._("Cannot run this job"), errorMsg=problem)
            return

        _logger.info("Starting background job %s (%s)", job_id, job_name)
        if not job.start():
            # Somebody asked it to stop before the worker got to it, or another
            # worker already has it. Either way it is not ours to run.
            _logger.info("Background job %s (%s) did not start, leaving it alone",
                         job_id, job_name)
            return
        try:
            record = env[job.model].browse(job.res_id)
            getattr(record, job.method)(job)
        except Exception as error:  # noqa: BLE001 - the outcome is recorded on the job
            _logger.error("Background job %s (%s) failed", job_id, job_name, exc_info=True)
            cr.rollback()
            register_exception(
                'Background Job: %s' % job_name,
                job.method,
                {'model': job.model, 'res_id': job.res_id, 'job_id': job_id},
                db_name,
                uid,
                error,
            )
            # The method already had whatever effect it had before failing, so
            # the job is not run again; it is marked and left to be read.
            job.abort(statusMsg=env._("Unexpected exception!"), errorMsg=traceback.format_exc())
            return

        state, completion_rate = job.get_current_state()
        _logger.info("Background job %s (%s) returned with state %s at %s%%",
                     job_id, job_name, state, completion_rate)
        if state == 'started':
            job.end()
        cr.commit()
