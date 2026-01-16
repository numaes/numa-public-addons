from . import models
from . import utils

def post_init_hook(env):
    """
    Hook executed after module installation/update.
    Triggers the recovery of any pending asynchronous jobs.
    """
    env['numa.asynch.job']._recover_pending_jobs()
