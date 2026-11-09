"""Private POSIX interprocess lock for one managed Pod.

Every managed worker and its watchdog must use the same lock path. The caller
must hold the lock throughout live status checks and any state transition.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat

try:
    import fcntl
except ImportError:
    fcntl = None


class WorkerLockError(RuntimeError):
    pass


@contextmanager
def pod_lock(state_dir, pod_id):
    """Yield False when another process holds the lock; otherwise hold it."""
    if fcntl is None:
        raise WorkerLockError('POSIX file locking is unavailable.')
    if not isinstance(pod_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', pod_id):
        raise WorkerLockError('Invalid Pod identity.')
    root = Path(state_dir)
    if root.is_symlink() or not root.is_dir():
        raise WorkerLockError('Unsafe lock directory.')
    info = root.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise WorkerLockError('Lock directory is not private and owned by this user.')
    lock_name = 'pod-' + hashlib.sha256(pod_id.encode('ascii')).hexdigest() + '.lock'
    path = root / lock_name
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) |
                     getattr(os, 'O_CLOEXEC', 0), 0o600)
    except OSError:
        raise WorkerLockError('Unable to open the Pod lock safely.') from None
    acquired = False
    try:
        item = os.fstat(fd)
        if not stat.S_ISREG(item.st_mode) or item.st_uid != os.getuid() or item.st_mode & 0o077:
            raise WorkerLockError('Unsafe Pod lock file.')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
