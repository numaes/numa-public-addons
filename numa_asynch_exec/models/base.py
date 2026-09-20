# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from odoo import models

from ..proxies import AsynchProxy, AwaitProxy


class Base(models.AbstractModel):
    """Give every model a way to run one of its methods in the background."""
    _inherit = 'base'

    def asynch_exec(self, retry=0, retry_delay=0):
        """Return a proxy that turns the next method call into a background job.

        The call returns as soon as the job is stored; the method itself runs
        in a worker thread once the current transaction commits.

        :param retry: how many times to retry on failure. -1 retries forever,
            which is meant for system-level polling threads only: every attempt
            reuses the same job row, but nothing ever stops it.
        :param retry_delay: milliseconds to wait before each attempt
        :return: an ``AsynchProxy``

        Example::

            records.asynch_exec(retry=3, retry_delay=500).some_heavy_method(arg)
        """
        return AsynchProxy(self, retry=retry, retry_delay=retry_delay)

    def job_wait(self, retry=0, retry_delay=0):
        """Return a proxy that chains background jobs, each waiting for the last.

        Each call creates a job that waits for the previous one. Calling
        ``job_wait()`` again in the middle of a chain runs the next method
        *alongside* the previous one instead of after it, and the call that
        follows waits for both.

        :param retry: how many times to retry each job of the chain on failure
        :param retry_delay: milliseconds to wait before each attempt
        :return: an ``AwaitProxy``

        Examples::

            # second runs after first
            records.job_wait().first().second()

            # first and second run together, third waits for both
            records.job_wait().first().job_wait().second().third()

            # first and second together, then third, then fourth
            records.job_wait().first().job_wait().second().third().fourth()
        """
        return AwaitProxy(self, retry=retry, retry_delay=retry_delay)
