# -*- coding: utf-8 -*-
# Part of NUMA Extreme Systems. See LICENSE file for full copyright and licensing details.

from . import models
from . import proxies
from . import utils


def post_init_hook(env):
    """Queue the jobs that were pending when the module was last stopped."""
    env['numa.asynch.job']._recover_pending_jobs()
