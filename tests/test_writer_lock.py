"""Single-writer lock guard for the shared NAS-hosted DB.

When Keith's Mac and Hermes both point ORBIT_HOME at the NAS, two simultaneous
DB writes can corrupt the SQLite file over a network mount. writer_lock() is a
context manager that serializes writers via flock. A second holder must fail
fast (non-blocking) rather than risk a concurrent write.
"""
from __future__ import annotations
from pathlib import Path

import pytest

from orbit.locking import writer_lock, LockHeld


def test_lock_acquires_and_releases(tmp_path):
    with writer_lock(tmp_path):
        pass  # should not raise
    # After release, re-acquire must succeed.
    with writer_lock(tmp_path):
        pass


def test_lock_is_exclusive(tmp_path):
    with writer_lock(tmp_path):
        # A second non-blocking acquire on the SAME home must refuse.
        with pytest.raises(LockHeld):
            with writer_lock(tmp_path, blocking=False):
                pass


def test_lockfile_lives_in_home(tmp_path):
    with writer_lock(tmp_path):
        assert (tmp_path / ".writer.lock").exists()


def test_different_homes_dont_collide(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    with writer_lock(a):
        with writer_lock(b, blocking=False):  # different home, no contention
            pass
