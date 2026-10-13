"""Linux advisory locks shared by workers, writes, and workspace maintenance.

Order: workspace gate -> experiment locks -> SQLite transaction. The gate is
reentrant within one thread. An exclusive upgrade is forbidden. Maintenance
never waits for a worker; the operator gets an actionable rejection instead.
"""
from contextlib import contextmanager
import fcntl
import threading

_local = threading.local()

class MaintenanceBusy(ValueError):
    pass

@contextmanager
def gate(root, exclusive=False):
    path = str(root / 'workspace.lock')
    held = getattr(_local, 'held', None)
    if held is None:
        held = _local.held = {}
    if path in held:
        if exclusive and not held[path]:
            raise MaintenanceBusy('cannot upgrade a workspace read lock')
        yield
        return
    with open(path, 'a+') as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MaintenanceBusy('Workspace busy: stop or pause workers and wait for maintenance to finish.') from None
        held[path] = exclusive
        try:
            yield
        finally:
            del held[path]
            fcntl.flock(lock, fcntl.LOCK_UN)
