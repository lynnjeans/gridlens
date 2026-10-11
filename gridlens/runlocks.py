"""Per-run OS file locks: held by the owning process for the whole run.

The OS releases a lock when its process exits, so recovery can tell an abandoned run
(lock acquirable) from a live one (lock held) without guessing from PIDs or ages.
"""

import fcntl
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


class RunLocks:
    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, name: str) -> Path:
        if not _NAME.match(name):
            raise ValueError("Invalid run lock name")
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory / f"{name}.lock"

    @contextmanager
    def hold(self, name: str) -> Iterator[None]:
        path = self._path(name)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            path.unlink(missing_ok=True)
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def is_abandoned(self, name: str) -> bool:
        """True when no live process holds the run's lock (including a missing lock file)."""
        path = self._path(name)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        path.unlink(missing_ok=True)
        return True
