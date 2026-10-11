"""Stable opaque host ID, created only when authorization is explicitly started."""

import fcntl
import os
from pathlib import Path
from uuid import UUID, uuid4

from gridlens.auth.credentials import atomic_json, protected_directory, read_protected


def get_or_create_host_id(directory: Path) -> str:
    protected_directory(directory)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(directory / ".host.lock", flags, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        path = directory / "host.json"
        if path.exists():
            identifier = read_protected(path)["ext_agent_host_id"]
            UUID(identifier.removeprefix("urn:uuid:"))
            return identifier
        identifier = f"urn:uuid:{uuid4()}"
        atomic_json(path, {"ext_agent_host_id": identifier})
        return identifier
