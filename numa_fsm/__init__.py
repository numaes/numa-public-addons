# -*- coding: utf-8 -*-

from . import controllers
from . import models


def post_init_hook(env):
    """
    Post-installation hook to initialize FSM timer processing task.
    
    This hook starts the continuous timer processing task using numa_asynch_exec
    with retry_count = -1 (infinite retries) and retry_delay = 1000ms (1 second).
    The task will run continuously, processing timers every second.
    """
    from .models.fsm import FSMTimer
    timer_model = env['fsm.timer']
    timer_model._schedule_timer_task()
