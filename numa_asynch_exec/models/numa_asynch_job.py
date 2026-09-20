# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.sql_db import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY

_logger = logging.getLogger(__name__)

# A job in one of these states has not run yet and can be picked up again
RECOVERABLE_STATES = ('pending', 'waiting')

# A database conflict says the job collided, not that it is wrong, so it gets
# its own budget of attempts rather than burning the ones the caller asked for
MAX_CONCURRENCY_RETRIES = 5


class NumaAsynchJob(models.Model):
    """One method call, persisted so that it survives the request that asked for it.

    The record holds everything a worker thread needs to rebuild the call:
    the model, the ids, the method name, its arguments and the context. It
    also holds what happened, so a failure is readable after the fact.
    """
    _name = 'numa.asynch.job'
    _description = "Asynchronous Job"
    _order = 'id'

    db_name = fields.Char(string="Database Name", help="Target database for execution")
    model_name = fields.Char(string="Model Name", help="Target Odoo model")
    res_ids = fields.Json(string="Resource IDs", help="Ids of the records to execute the method on")
    method_name = fields.Char(string="Method Name", help="Name of the method to call")
    args = fields.Json(string="Arguments", help="Positional arguments for the method")
    kwargs = fields.Json(string="Keyword Arguments", help="Keyword arguments for the method")
    context = fields.Json(string="Context", help="Serialized environment context")
    uid = fields.Many2one('res.users', string="User", ondelete='set null',
                          help="User that asked for the job; execution itself runs as superuser")

    max_retries = fields.Integer(
        string="Max Retries", default=0,
        help="How many times to retry on failure. -1 retries forever, which is meant for "
             "system-level polling threads only. Default: 0, no retry.")
    retry_count = fields.Integer(string="Retry Count", default=0, readonly=True)
    concurrency_retries = fields.Integer(
        string="Concurrency Retries", default=0, readonly=True,
        help="Attempts spent on database conflicts, which do not count as failures")
    retry_delay = fields.Integer(
        string="Retry Delay (ms)", default=0,
        help="Milliseconds to wait before each execution and each retry. Default: 0.")

    state = fields.Selection([
        ('pending', "Pending"),
        ('waiting', "Waiting for Dependencies"),
        ('running', "Running"),
        ('done', "Done"),
        ('failed', "Failed"),
    ], string="State", default='pending', index=True, required=True)
    error = fields.Text(string="Error", readonly=True,
                        help="Why the last attempt failed")

    dependency_ids = fields.One2many(
        'numa.asynch.job.dependency', 'job_id', string="Dependencies",
        help="Jobs that must complete before this job can execute")
    dependent_ids = fields.One2many(
        'numa.asynch.job.dependency', 'depends_on_id', string="Dependent Jobs",
        help="Jobs that wait for this one")
    has_dependencies = fields.Boolean(
        string="Has Dependencies", compute='_compute_has_dependencies',
        help="Whether this job waits for any other job")

    @api.depends('dependency_ids')
    def _compute_has_dependencies(self):
        for record in self:
            record.has_dependencies = bool(record.dependency_ids)

    @api.depends('model_name', 'method_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s.%s #%s" % (
                record.model_name or '?', record.method_name or '?', record.id)

    def action_requeue(self):
        """Put the selected jobs back in the queue, with a fresh budget.

        This is the way out for a job left in ``running`` by a process that
        died: nothing can tell such a job apart from one that is merely slow,
        so somebody has to say so.
        """
        finished = self.filtered(lambda job: job.state == 'done')
        if finished:
            raise UserError(self.env._(
                "%(count)s of the selected jobs already finished successfully, and running "
                "them again could repeat what they did. Unselect them, or pick only the jobs "
                "that are Failed, Waiting or Running.",
                count=len(finished)))
        for job in self:
            job.write({'retry_count': 0, 'concurrency_retries': 0, 'error': False})
            if job._all_dependencies_done():
                job.write({'state': 'pending'})
                job._queue()
            else:
                job.write({'state': 'waiting'})
        return True

    def _all_dependencies_done(self):
        """Tell whether every job this one waits for has finished successfully."""
        self.ensure_one()
        return all(dep.depends_on_id.state == 'done' for dep in self.dependency_ids)

    def _check_runnable(self):
        """Return why this job cannot run, or an empty string when it can.

        Everything that makes a job impossible rather than merely failing is
        checked here: a model that no longer exists, records that were
        deleted, a method that is not there.
        """
        self.ensure_one()
        if not self.model_name or self.model_name not in self.env:
            return "model %r is not in the registry" % self.model_name
        records = self.env[self.model_name].browse(self.res_ids or []).exists()
        if (self.res_ids or []) and not records:
            return "no target record left (model %s, ids %s)" % (self.model_name, self.res_ids)
        if not self.method_name:
            return "no method name"
        method = getattr(records, self.method_name, None)
        if method is None:
            return "method %r does not exist on %s" % (self.method_name, self.model_name)
        if not callable(method):
            return "%r is not callable on %s" % (self.method_name, self.model_name)
        return ""

    def _claim(self):
        """Move this job from a recoverable state to ``running``, atomically.

        The executor and the recovery cron can both hold the same job, so the
        transition is a conditional UPDATE: exactly one caller gets the row.

        :return: True when this caller owns the job
        """
        self.ensure_one()
        # Conditional UPDATE rather than write(): two callers must not both
        # see 'pending' and both run the method.
        self.env.cr.execute(
            "UPDATE numa_asynch_job SET state = 'running' WHERE id = %s AND state IN %s RETURNING id",
            [self.id, RECOVERABLE_STATES],
        )
        claimed = bool(self.env.cr.fetchone())
        self.invalidate_recordset(['state'])
        return claimed

    def _execute(self):
        """Call the method this job stands for.

        Runs as superuser so that system-level work is not stopped by
        company record rules; the requesting user stays on ``uid`` for audit.
        """
        self.ensure_one()
        records = self.env[self.model_name].with_context(**(self.context or {})).browse(self.res_ids or [])
        args = self.args if isinstance(self.args, list) else []
        kwargs = self.kwargs if isinstance(self.kwargs, dict) else {}
        return getattr(records, self.method_name)(*args, **kwargs)

    def _record_failure(self, error):
        """Store the failure and decide whether the job gets another attempt.

        The row is reused rather than copied: an unbounded retry (``-1``,
        which polling threads use) would otherwise grow the table forever.
        """
        self.ensure_one()
        message = "%s: %s" % (type(error).__name__, error)
        if isinstance(error, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY):
            # Two jobs touching the same row is normal, not a defect: the
            # loser of the race is told to come back, and the attempt is not
            # charged against max_retries.
            if self.concurrency_retries < MAX_CONCURRENCY_RETRIES:
                attempt = self.concurrency_retries + 1
                _logger.info("Asynchronous job %s hit a database conflict, retrying (%s of %s)",
                             self.id, attempt, MAX_CONCURRENCY_RETRIES)
                self.write({'state': 'pending', 'concurrency_retries': attempt, 'error': message})
                return
            _logger.warning("Asynchronous job %s kept losing database conflicts: %s",
                            self.id, message)
        if self.max_retries < 0 or self.retry_count < self.max_retries:
            attempt = self.retry_count + 1
            _logger.warning("Asynchronous job %s failed, retrying (attempt %s of %s): %s",
                            self.id, attempt, 'unbounded' if self.max_retries < 0 else self.max_retries,
                            message)
            self.write({'state': 'pending', 'retry_count': attempt,
                        'concurrency_retries': 0, 'error': message})
        else:
            _logger.warning("Asynchronous job %s failed, no retry left: %s", self.id, message)
            self.write({'state': 'failed', 'error': message})

    def _trigger_dependents(self):
        """Queue the jobs that were waiting for this one, once they are free."""
        for record in self:
            for dependency in record.dependent_ids:
                dependent = dependency.job_id
                if dependent.state == 'waiting' and dependent._all_dependencies_done():
                    dependent._release()

    def _release(self):
        """Move a waiting job to ``pending`` and queue it, at most once.

        Several dependencies finishing at the same time would otherwise each
        queue the same job.
        """
        self.ensure_one()
        # Conditional UPDATE: the last dependency to finish wins, the others
        # find the row already released and do nothing.
        self.env.cr.execute(
            "UPDATE numa_asynch_job SET state = 'pending' WHERE id = %s AND state = 'waiting' RETURNING id",
            [self.id],
        )
        released = bool(self.env.cr.fetchone())
        self.invalidate_recordset(['state'])
        if released:
            _logger.info("Asynchronous job %s has all its dependencies, queueing it", self.id)
            self._queue()
        return released

    def _next_delay(self):
        """Milliseconds to wait before the next attempt.

        A job that keeps losing database conflicts backs off, so that two
        jobs fighting over the same row stop colliding on every try.
        """
        self.ensure_one()
        if self.concurrency_retries:
            return self.retry_delay + min(2 ** self.concurrency_retries, 32) * 100
        return self.retry_delay

    def _queue(self):
        """Ask the executor to run this job once the transaction is committed.

        Queueing before the commit would hand the worker a job it cannot see.
        """
        self.ensure_one()
        from ..utils import submit_job
        job_id, db_name, context, delay = self.id, self.db_name, self.context, self._next_delay()
        self.env.cr.postcommit.add(lambda: submit_job(job_id, db_name, context, delay))

    @api.model
    def _recover_pending_jobs(self):
        """Queue every job that has not run yet.

        Called on install or update, and by the recovery cron: a job that was
        queued in a process that died is only in the database, and nothing
        else would ever pick it up.

        :return: the number of jobs queued
        """
        jobs = self.sudo().search([('state', 'in', RECOVERABLE_STATES)])
        queued = self.browse()
        for job in jobs:
            if job._all_dependencies_done():
                job._queue()
                queued |= job
            elif job.state != 'waiting':
                job.write({'state': 'waiting'})
        if queued:
            _logger.info("Recovering %s asynchronous job(s)", len(queued))
        return len(queued)
