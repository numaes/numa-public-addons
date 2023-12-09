# -*- coding: utf-8 -*-

import odoo
from odoo import models, fields, api, modules, SUPERUSER_ID

from odoo.tools.translate import _

import threading
import datetime
import time

import sys
import traceback

import logging

_logger = logging.getLogger(__name__)


class BackgroundJob(models.Model):
    _name = "res.background_job"
    _description = '''
        Background Job Tasks
    '''

    name = fields.Char('Job name')
    state = fields.Selection([
        ('init', 'Initializing'),
        ('started', 'Started'),
        ('ended', 'Ended'),
        ('aborting', 'Aborting ...'),
        ('aborted', 'Aborted'),
    ], string="State", required=True, default='init')

    model = fields.Char('Model', required=True)
    res_id = fields.Integer('Resource ID', required=True)
    method = fields.Char('Method to call', required=True)
    reference_id = fields.Integer('Reference id')
    completion_rate = fields.Integer("Completion rate [%]")
    current_status = fields.Text('Current status')
    error = fields.Text('Error message')

    initialized_on = fields.Datetime('Initialized on')
    started_on = fields.Datetime('Started on')
    ended_on = fields.Datetime('Ended on')
    aborted_on = fields.Datetime('Aborted on')

    def create(self, vals):
        """
        Start a new backgroud job in a thread. The thread will be created automatically
        In order to execute the job, a model instance method should be specified through
        model name, resource id and <run_method> name
        The method will be called with the following signature:
            def <run_method>(self, bkJob)

        where bkJob is the background job.
        The run_method can execute the job just in one transaction, setting before
        returning the bkJob to ended or completion rate >= 100. Job completion
        could be updated using update_status on bkJob. In the case of long
        lasting jobs, update_status could be called several times in order to give
        the user the chance to be informed of the progress. In the end, either
        bkJob end method could be called or completion rate >= 100 could be used

        In the case run_method want to be used using several consecutive transactions,
        run_method should return on each intermediate transaction, keeping enough
        status information to continue the job in the next invocation. Completation
        rate and current status could be updated any time using update_status on bkJob

        Completed or aborted jobs will be cleaned up automatically once a week, and
        thus the user should not carry out any cleaning action on job completion or
        abortion.
        """

        newVals = vals.copy()
        newVals['initialized_on'] = fields.Datetime.now()
        newVals['started_on'] = False
        newVals['ended_on'] = False
        newVals['aborted_on'] = False
        if 'state' in newVals:
            del newVals['state']

        newJob = super(BackgroundJob, self).create(newVals)
        newJobId = newJob.id

        self.env.cr.commit()

        BackgroundThread(self.env.cr.dbname,
                         self.env.user.id,
                         vals['name'],
                         newJobId,
                         context=self.env.context)

        return newJob

    def refresh_state(self):
        busModel = self.env['bus.bus']

        for job in self:
            channel = job
            message = dict(
                id=job.id,
                completion_rate=job.completion_rate,
                state=job.state,
                current_status=job.current_status,
                error=job.error,
                initialized_on=str(job.initialized_on),
                started_on=str(job.started_on),
                ended_on=str(job.ended_on),
                aborted_on=str(job.aborted_on),
            )
            self.env.cr.commit()
            busModel._sendone('res.background_job', 'background_job.state_change', message)
            self.env.cr.commit()

    def start(self, statusMsg=None):
        ids = [o.id for o in self]
        self.env.flush_all()

        db = odoo.modules.registry.Registry(self.env.cr.dbname)
        if db:
            cr = db.cursor()
            env = api.Environment(cr, SUPERUSER_ID, self.env.context)
            bkJobObj = env['res.background_job']
            bkJobObj.env.invalidate_all()
            for job in bkJobObj.browse(ids):
                if job.state == 'init':
                    job.write({
                        'started_on': fields.Datetime.now(),
                        'state': 'started',
                        'current_status': statusMsg or _('Started'),
                        'error': False,
                        'completion_rate': 0,
                    })
                    job.flush_recordset()
                cr.commit()
                job.refresh_state()
            cr.close()

    def end(self, statusMsg=None, errorMsg=None):
        ids = [o.id for o in self]
        self.env.flush_all()

        db = odoo.modules.registry.Registry(self.env.cr.dbname)
        if db:
            cr = db.cursor()
            env = api.Environment(cr, SUPERUSER_ID, self.env.context)
            bkJobObj = env['res.background_job']
            bkJobObj.env.flush_all()
            for job in bkJobObj.browse(ids):
                if job.state not in ['ended', 'aborted']:
                    if errorMsg is not None:
                        job.error = errorMsg

                    job.write({
                        'ended_on': fields.Datetime.now(),
                        'current_status': statusMsg or '',
                        'state': 'ended',
                    })
                    job.flush_recordset()
                cr.commit()
                job.refresh_state()
            cr.close()

    def abort(self, statusMsg=None, errorMsg=None):
        ids = [o.id for o in self]
        self.env.flush_all()

        db = odoo.modules.registry.Registry(self.env.cr.dbname)
        if db:
            cr = db.cursor()
            env = api.Environment(cr, SUPERUSER_ID, self.env.context)
            bkJobObj = env['res.background_job']
            bkJobObj.env.invalidate_all()
            for job in bkJobObj.browse(ids):
                if job.state in ('started', 'aborting'):
                    if statusMsg is not None:
                        job.current_status = statusMsg
                    if errorMsg is not None:
                        job.error = errorMsg

                    job.write({
                        'aborted_on': fields.Datetime.now(),
                        'state': 'aborted',
                    })
                    job.flush_recordset()
                cr.commit()
                job.refresh_state()
            cr.close()

    def try_to_abort(self, statusMsg=None):
        ids = [o.id for o in self]
        self.env.flush_all()

        db = odoo.modules.registry.Registry(self.env.cr.dbname)
        if db:
            cr = db.cursor()
            env = api.Environment(cr, SUPERUSER_ID, self.env.context)
            bkJobObj = env['res.background_job']
            bkJobObj.env.flush_all()
            for job in bkJobObj.browse(ids):
                if job.state == 'started':
                    job.write({
                        'aborted_on': fields.Datetime.now(),
                        'current_status': statusMsg or _('Aborting ...'),
                        'state': 'aborting',
                        'error': False,
                    })
                    job.flush_recordset()
                cr.commit()
                job.refresh_state()
            cr.close()

    def was_aborted(self):
        self.ensure_one()
        self.env.flush_all()

        bkjId = self.id

        wasAborted = True
        db = odoo.modules.registry.Registry(self.env.cr.dbname)
        if db:
            cr = db.cursor()
            env = api.Environment(cr, SUPERUSER_ID, self.env.context)
            bkJobObj = env['res.background_job']
            bkJobObj.env.invalidate_all()
            job = bkJobObj.browse(bkjId)
            wasAborted = job.state not in ['started']
            cr.commit()
            cr.close()

        return wasAborted

    def update_status(self, rate=None, statusMsg=None, errorMsg=None):
        ids = [o.id for o in self]
        self.env.flush_all()

        db = odoo.modules.registry.Registry(self.env.cr.dbname)
        if db:
            cr = db.cursor()
            env = api.Environment(cr, SUPERUSER_ID, self.env.context)
            bkJobObj = env['res.background_job']
            bkJobObj.env.invalidate_all()
            for job in bkJobObj.browse(ids):
                if job.state == 'started':
                    if statusMsg is not None:
                        job.current_status = statusMsg
                    if errorMsg is not None:
                        job.error = errorMsg
                    if rate is not None:
                        job.completion_rate = rate
                    job.flush_recordset()
                cr.commit()
                job.refresh_state()
            cr.close()

    def get_current_state(self):
        self.ensure_one()
        self.env.flush_all()

        bjId = self.id
        state = None
        completionRate = 0

        db = odoo.modules.registry.Registry(self.env.cr.dbname)
        if db:
            cr = db.cursor()
            env = api.Environment(cr, SUPERUSER_ID, self.env.context)
            bkJobObj = env['res.background_job']
            bkJobObj.env.flush_all()
            job = bkJobObj.browse(bjId)
            state = job.state
            completionRate = job.completion_rate
            cr.commit()
            cr.close()

        return state, completionRate

    def prune(self):
        _logger.info(_("Cleaning up background jobs"))

        now = datetime.datetime.now()
        lastWeek_dt = now - datetime.timedelta(seconds=3600 * 24 * 8)
        lastWeek = lastWeek_dt.strftime("%Y-%m-%d 00:00:00")
        _logger.info(_("Cleaning up background jobs before %s") % lastWeek)
        jobsToUnlink = self.search(['|', ('initialized_on', '=', False), ('initialized_on', '<', lastWeek)])
        if jobsToUnlink:
            _logger.info(_("Cleaning up %d background jobs") % len(jobsToUnlink))
            jobsToUnlink.unlink()


class BackgroundThread(threading.Thread):
    def __init__(self, dbName, uid, jobName, jobId, context=None):
        context = context or {}

        super(BackgroundThread, self).__init__()

        self.jobName = jobName
        self.dbName = dbName
        self.jobId = jobId
        self.context = context
        self.uid = uid
        self.start()

    def run(self):
        attemptCount = 0
        while attemptCount < 10:
            db = odoo.modules.registry.Registry(self.dbName)
            if db:
                cr = db.cursor()
                env = api.Environment(cr, self.uid, self.context)
                bkJobObj = env['res.background_job']
                bkJob = bkJobObj.browse(self.jobId)
                if bkJob.exists():
                    bkJob.start()
                    try:
                        modelObj = env[bkJob.model]
                        modelInstance = modelObj.browse(bkJob.res_id)
                        method = getattr(modelInstance, bkJob.method)
                        if method:
                            method(bkJob)
                            state, completionRate = bkJob.get_current_state()
                            _logger.info(_("Ending with completion_rate: %d, state=%s") %
                                         (completionRate, state))

                            if state == 'started' and completionRate >= 100:
                                bkJob.end()
                        else:
                            bkJob.abort(
                                statusMsg=_("No method defined!"))
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        exceptionLines = traceback.format_exception(exc_type, exc_value, exc_traceback)

                        cr.rollback()

                        bkJob = bkJobObj.browse(self.jobId)
                        bkJob.abort(
                            statusMsg=_('Unexpected exception!'),
                            errorMsg='\n'.join(exceptionLines))

                    cr.commit()
                    cr.close()
                    break
                else:
                    cr.rollback()
                    cr.close()
                    attemptCount += 1
                    time.sleep(1)
