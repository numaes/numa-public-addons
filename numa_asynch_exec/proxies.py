# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.
"""The fluent interface: what turns ``records.asynch_exec().method()`` into a job.

Neither proxy executes anything. They translate an attribute access into a
``numa.asynch.job`` record, and the worker thread does the rest.
"""

import logging

from odoo import Command

from .utils import make_json_serializable

_logger = logging.getLogger(__name__)

JOB_MODEL = 'numa.asynch.job'


def _job_values(recordset, method_name, args, kwargs, retry, retry_delay):
    """Build the values of the job that stands for one method call."""
    return {
        'db_name': recordset.env.cr.dbname,
        'model_name': recordset._name,
        'res_ids': recordset.ids,
        'method_name': method_name,
        'args': make_json_serializable(args),
        'kwargs': make_json_serializable(kwargs),
        'context': make_json_serializable(recordset.env.context),
        'uid': recordset.env.uid,
        'max_retries': retry,
        'retry_delay': retry_delay,
    }


class AsynchProxy:
    """Turns the next method call on a recordset into a single background job."""

    def __init__(self, recordset, retry=0, retry_delay=0):
        self.recordset = recordset
        self.retry = retry
        self.retry_delay = retry_delay

    def __getattr__(self, name):
        if name.startswith('__'):
            # Never let a dunder lookup, from copy, pickle or the interpreter
            # itself, be mistaken for a method the caller wants to run.
            raise AttributeError(name)

        def _enqueue(*args, **kwargs):
            job = self.recordset.env[JOB_MODEL].sudo().create(
                _job_values(self.recordset, name, args, kwargs, self.retry, self.retry_delay))
            _logger.debug("Asynchronous job %s created for %s.%s",
                          job.id, self.recordset._name, name)
            job._queue()
            # The id, not the sudo recordset: the caller gets something to
            # follow the job with, not a handle that bypasses its own rights.
            return job.id

        return _enqueue


class AwaitProxy:
    """Builds a chain of background jobs, each waiting for the one before it.

    The chain is created as it is written: every call stores its job right
    away, so no terminal call is needed. ``job_wait()`` in the middle of a
    chain marks the next call as parallel to the previous one; whatever comes
    after that waits for every branch opened since.
    """

    def __init__(self, recordset, retry=0, retry_delay=0):
        self.recordset = recordset
        self.retry = retry
        self.retry_delay = retry_delay
        # Jobs the next sequential call must wait for
        self._barrier = []
        # Jobs created by the branches opened since the last sequential call
        self._branch_heads = []
        # What a branch starts from: the dependencies of the last sequential job
        self._branch_base = []
        self._parallel_next = False

    def job_wait(self, retry=None, retry_delay=None):
        """Run the next call alongside the previous one instead of after it.

        :param retry: overrides the retry count from this point on
        :param retry_delay: overrides the delay from this point on
        :return: this proxy, so the chain keeps reading left to right
        """
        if retry is not None:
            self.retry = retry
        if retry_delay is not None:
            self.retry_delay = retry_delay
        self._parallel_next = True
        return self

    def __getattr__(self, name):
        if name.startswith('__'):
            # A dunder lookup comes from the interpreter, never from a caller
            # that wants that method run.
            raise AttributeError(name)

        def _chain(*args, **kwargs):
            if self._parallel_next:
                depends_on = list(self._branch_base)
                self._parallel_next = False
                job = self._create(name, args, kwargs, depends_on)
                self._branch_heads.append(job.id)
            else:
                depends_on = self._barrier + self._branch_heads
                job = self._create(name, args, kwargs, depends_on)
                self._branch_base = list(depends_on)
                self._barrier = [job.id]
                self._branch_heads = []
            return self

        return _chain

    def _create(self, method_name, args, kwargs, depends_on):
        """Store one job of the chain, waiting on the given jobs."""
        values = _job_values(self.recordset, method_name, args, kwargs,
                             self.retry, self.retry_delay)
        if depends_on:
            values['state'] = 'waiting'
            values['dependency_ids'] = [
                Command.create({'depends_on_id': job_id}) for job_id in depends_on
            ]
        job = self.recordset.env[JOB_MODEL].sudo().create(values)
        _logger.debug("Asynchronous job %s created for %s.%s, waiting for %s",
                      job.id, self.recordset._name, method_name, depends_on or 'nothing')
        if not depends_on:
            job._queue()
        return job
