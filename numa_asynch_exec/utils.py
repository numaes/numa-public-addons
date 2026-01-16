import threading
from concurrent.futures import ThreadPoolExecutor
from odoo.tools import config

_executor_lock = threading.Lock()
_executor = None

def get_asynch_executor():
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                max_workers = int(config.get('numa_asynch_max_threads', 5))
                _executor = ThreadPoolExecutor(max_workers=max_workers)
    return _executor
