import threading
from concurrent.futures import ThreadPoolExecutor
from odoo.tools import config

# Thread-safe global executor instance
_executor_lock = threading.Lock()
max_workers = int(config.get('numa_asynch_max_threads', 5))
_executor = ThreadPoolExecutor(
    max_workers=max_workers,
    thread_name_prefix='numa_asynch_exec'
)

def get_asynch_executor():
    """
    Returns the global ThreadPoolExecutor instance, initializing it if necessary.
    The number of workers can be configured in odoo.conf via 'numa_asynch_max_threads'.
    
    :return: ThreadPoolExecutor instance
    """
    global _executor
    return _executor
