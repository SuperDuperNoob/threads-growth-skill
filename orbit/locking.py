"""Single-writer file lock for the shared NAS-hosted Orbit home.

Both Keith's Mac and the Hermes agent may point ORBIT_HOME at the same NAS
directory. SQLite over a network mount can corrupt under concurrent writes, so
any DB-mutating command should run inside writer_lock() to serialize writers.

Uses fcntl.flock on a lockfile in the home dir. flock is advisory and
process-associated — released automatically if the holder dies, which matters
for an unattended agent that might be killed mid-run.
"""
from __future__ import annotations
import fcntl
from contextlib import contextmanager
from pathlib import Path


class LockHeld(Exception):
    """Raised when a non-blocking acquire fails because another writer holds it."""


@contextmanager
def writer_lock(home: Path, *, blocking: bool = True):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    lockfile = home / ".writer.lock"
    flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
    f = lockfile.open("w")
    try:
        try:
            fcntl.flock(f.fileno(), flags)
        except BlockingIOError as e:
            raise LockHeld(f"another writer holds {lockfile}") from e
        yield
    finally:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()
