from . import models
from . import utils

def post_init_hook(env):
    env['numa.asynch.job']._recover_pending_jobs()
