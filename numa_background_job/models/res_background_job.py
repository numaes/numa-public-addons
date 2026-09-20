# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

import datetime
import logging

from odoo import SUPERUSER_ID, api, fields, models
from odoo.fields import Domain
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

JOB_MODEL = 'res.background_job'

# What the owner's browser subscribes to
NOTIFICATION_TYPE = 'res.background_job/state'

# A job in one of these states is over
FINISHED_STATES = ('ended', 'aborted')

# Finished jobs are deleted after this many days
DEFAULT_RETENTION_DAYS = 8

# Overrides DEFAULT_RETENTION_DAYS when set; 0 disables the cleanup
RETENTION_DAYS_PARAM = 'numa_background_job.retention_days'

# Fields the owner's browser is told about
NOTIFIED_FIELDS = (
    'name', 'state', 'completion_rate', 'current_status', 'error',
    'initialized_on', 'started_on', 'ended_on', 'aborted_on',
)


class ResBackgroundJob(models.Model):
    """A long task, run in a thread of its own so the interface is not blocked.

    A job names a record and a method; once the transaction that created it
    commits, a worker thread calls ``method(job)``. The method reports back
    through :meth:`update_status`, and says it is over by calling :meth:`end`
    or by reaching a completion rate of 100.

    Progress is written on a cursor of its own, so the user sees it while the
    job's own transaction is still open, and still sees it if that transaction
    ends up rolling back.
    """
    _name = 'res.background_job'
    _description = "Background Job"
    _order = 'id desc'

    name = fields.Char(string="Job name", required=True)
    state = fields.Selection([
        ('init', "Initializing"),
        ('started', "Started"),
        ('ended', "Ended"),
        ('aborting', "Aborting ..."),
        ('aborted', "Aborted"),
    ], string="State", required=True, default='init', index=True)

    user_id = fields.Many2one(
        'res.users', string="Owner", required=True, index=True, ondelete='cascade',
        default=lambda self: self.env.user,
        help="Who asked for the job. Only this user sees it, and only this user is told how it goes.")

    model = fields.Char(string="Model", required=True)
    res_id = fields.Integer(string="Resource ID", required=True)
    method = fields.Char(string="Method to call", required=True)
    reference_id = fields.Integer(string="Reference id",
                                  help="Free field for the caller to find its own record again")
    completion_rate = fields.Integer(string="Completion rate [%]")
    current_status = fields.Text(string="Current status")
    error = fields.Text(string="Error message")

    initialized_on = fields.Datetime(string="Initialized on", readonly=True)
    started_on = fields.Datetime(string="Started on", readonly=True)
    ended_on = fields.Datetime(string="Ended on", readonly=True)
    aborted_on = fields.Datetime(string="Aborted on", readonly=True)

    @api.model
    def _launch(self, name, record, method, reference_id=None):
        """Create and start a background job on behalf of the current user.

        This is the way to start a job. It goes through ``sudo()`` because
        ordinary users cannot write this table: a row in it names a method the
        server will call, so letting users write one would turn every private
        method into an RPC entry point. The owner is passed explicitly, since
        under ``sudo()`` the current user is no longer the one who asked.

        It is deliberately not callable over RPC.

        :param name: what to call the job, shown to the user
        :param record: the record the method is called on
        :param method: name of the method, called as ``method(job)``
        :param reference_id: free value for the caller to find its own record
            again; defaults to the record's id
        :return: the created job, as the caller's own user sees it
        """
        record.ensure_one()
        job = self.sudo().create({
            'name': name,
            'model': record._name,
            'res_id': record.id,
            'method': method,
            'reference_id': record.id if reference_id is None else reference_id,
            'user_id': self.env.uid,
        })
        return job.with_env(self.env)

    @api.model_create_multi
    def create(self, vals_list):
        """Store the jobs and hand each of them to a thread after the commit."""
        for vals in vals_list:
            vals.pop('state', None)
            vals.update({
                'initialized_on': fields.Datetime.now(),
                'started_on': False,
                'ended_on': False,
                'aborted_on': False,
            })
        jobs = super().create(vals_list)
        jobs._spawn()
        return jobs

    def _spawn(self):
        """Ask for a worker thread once the current transaction commits.

        Starting before the commit would hand the thread a job it cannot see,
        and would run it even if the transaction ends up rolling back.
        """
        from ..worker import start_worker
        db_name, uid, context = self.env.cr.dbname, self.env.uid, dict(self.env.context)
        for job in self:
            arguments = (db_name, uid, job.name, job.id, context)
            self.env.cr.postcommit.add(lambda arguments=arguments: start_worker(*arguments))

    # -- the state of a job, written apart from the job's own transaction ----

    def _status_cursor(self):
        """Open the cursor the status is written on.

        Its own, so that progress is visible while the job's transaction is
        still open, and survives that transaction rolling back.
        """
        return Registry(self.env.cr.dbname).cursor()

    def _write_status(self, values, allowed_states=None):
        """Write a status change and tell the owner about it.

        :param values: what to write on each job
        :param allowed_states: only act on jobs currently in one of these
        :return: the ids actually written
        """
        if not self:
            return []
        # The write itself happens as superuser, on a cursor of its own, so
        # the caller's rights have to be checked here: otherwise anybody could
        # drive anybody else's job through start(), end() or try_to_abort().
        self.check_access('write')
        ids, context = self.ids, dict(self.env.context)
        self.env.flush_all()
        with self._status_cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, context)
            jobs = env[JOB_MODEL].browse(ids).exists()
            if allowed_states is not None:
                jobs = jobs.filtered(lambda job: job.state in allowed_states)
            if jobs:
                jobs.write(values)
                jobs._notify_owner()
                # Own cursor, own transaction: committing here is the whole
                # point, the user has to see the progress now.
                cr.commit()
            written = jobs.ids
        self.invalidate_recordset()
        return written

    def _read_status(self, field_names):
        """Read a job as the database has it, outside our own transaction."""
        self.ensure_one()
        # Same reason as in _write_status: the read below is a superuser read.
        self.check_access('read')
        self.env.flush_all()
        with self._status_cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, dict(self.env.context))
            job = env[JOB_MODEL].browse(self.id).exists()
            return {name: job[name] for name in field_names} if job else {}

    def _notify_owner(self):
        """Tell whoever asked for the job how it is going.

        The channel is the owner's user record, not a string anybody could
        guess: a job's progress, and the traceback in ``error``, are nobody
        else's business.
        """
        bus = self.env['bus.bus']
        for job in self:
            if not job.user_id:
                continue
            bus._sendone(job.user_id, NOTIFICATION_TYPE, job._notification_payload())

    def _notification_payload(self):
        """Build what the owner's browser receives."""
        self.ensure_one()
        payload = {'id': self.id}
        for name in NOTIFIED_FIELDS:
            value = self[name]
            if isinstance(value, datetime.datetime):
                # The browser turns this back into the user's own timezone
                value = fields.Datetime.to_string(value)
            payload[name] = value
        return payload

    # -- what a running job calls -------------------------------------------

    def start(self, statusMsg=None):
        """Mark the job as running. Called by the worker, not by the method."""
        return self._write_status({
            'state': 'started',
            'started_on': fields.Datetime.now(),
            'current_status': statusMsg or self.env._("Started"),
            'error': False,
            'completion_rate': 0,
        }, allowed_states=('init',))

    def update_status(self, rate=None, statusMsg=None, errorMsg=None):
        """Report progress. Anything left as None is left as it was."""
        values = {}
        if rate is not None:
            values['completion_rate'] = rate
        if statusMsg is not None:
            values['current_status'] = statusMsg
        if errorMsg is not None:
            values['error'] = errorMsg
        if not values:
            return []
        return self._write_status(values, allowed_states=('started',))

    def end(self, statusMsg=None, errorMsg=None):
        """Mark the job as finished."""
        values = {'state': 'ended', 'ended_on': fields.Datetime.now(),
                  'current_status': statusMsg or ''}
        if errorMsg is not None:
            values['error'] = errorMsg
        return self._write_status(values, allowed_states=('init', 'started', 'aborting'))

    def try_to_abort(self, statusMsg=None):
        """Ask a job to stop. The job decides when, through was_aborted.

        Allowed before the worker has picked the job up as well: the worker
        checks that its start() took effect before calling anything.
        """
        return self._write_status({
            'state': 'aborting',
            'aborted_on': fields.Datetime.now(),
            'current_status': statusMsg or self.env._("Aborting ..."),
            'error': False,
        }, allowed_states=('init', 'started'))

    def abort(self, statusMsg=None, errorMsg=None):
        """Mark the job as stopped.

        Allowed from ``init`` too: a job the worker finds it cannot run never
        started, and leaving it there would keep it forever in a state that
        says it is about to run.
        """
        values = {'state': 'aborted', 'aborted_on': fields.Datetime.now()}
        if statusMsg is not None:
            values['current_status'] = statusMsg
        if errorMsg is not None:
            values['error'] = errorMsg
        return self._write_status(values, allowed_states=('init', 'started', 'aborting'))

    def was_aborted(self):
        """Tell a running job whether it should stop.

        True as soon as somebody asked it to stop, and also when the job is no
        longer running at all.
        """
        self.ensure_one()
        status = self._read_status(['state'])
        return status.get('state') not in ('started',)

    def get_current_state(self):
        """Return the job's ``(state, completion_rate)`` as stored."""
        self.ensure_one()
        status = self._read_status(['state', 'completion_rate'])
        return status.get('state'), status.get('completion_rate', 0)

    # -- housekeeping --------------------------------------------------------

    def _check_runnable(self):
        """Return why this job cannot run, or an empty string when it can."""
        self.ensure_one()
        if not self.model or self.model not in self.env:
            return "model %r is not in the registry" % self.model
        record = self.env[self.model].browse(self.res_id).exists()
        if not record:
            return "no target record (model %s, id %s)" % (self.model, self.res_id)
        method = getattr(record, self.method, None) if self.method else None
        if method is None:
            return "method %r does not exist on %s" % (self.method, self.model)
        if not callable(method):
            return "%r is not callable on %s" % (self.method, self.model)
        return ""

    @api.model
    def prune(self):
        """Delete the jobs that finished long enough ago.

        Only finished jobs: a job still running is not stale, however long it
        has been at it. This is the method the daily cron calls.
        """
        days = self.env['ir.config_parameter'].sudo().get_int(
            RETENTION_DAYS_PARAM, DEFAULT_RETENTION_DAYS)
        if days <= 0:
            _logger.info("Background job cleanup is disabled (%s = %s)", RETENTION_DAYS_PARAM, days)
            return True

        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        domain = Domain('state', 'in', FINISHED_STATES) & (
            Domain('initialized_on', '=', False) | Domain('initialized_on', '<', limit))
        stale = self.search(domain)
        _logger.info("Cleaning up %d background job(s) finished before %s", len(stale), limit)
        stale.unlink()
        return True
