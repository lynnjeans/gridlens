"""Owner-only, atomic credential storage separate from the research database."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from gridlens.contracts import AccountSummary, CredentialRecord
from gridlens.errors import AppError


def registration_id(record: CredentialRecord) -> str:
    return hashlib.sha256(
        json.dumps(
            [record.issuer, record.subject, record.client_id], separators=(",", ":")
        ).encode()
    ).hexdigest()


def protected_directory(path: Path) -> None:
    if path.is_symlink():
        raise AppError("CREDENTIAL_STORAGE_UNSAFE", "Credential directory cannot be a symlink.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise AppError("CREDENTIAL_STORAGE_UNSAFE", "Credential directory has a different owner.")
    path.chmod(0o700)


def atomic_json(path: Path, value: dict) -> None:
    protected_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_protected(path: Path) -> dict:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        stat = os.fstat(fd)
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise AppError("CREDENTIAL_STORAGE_UNSAFE", "Credential file must be owner-only.")
        with os.fdopen(fd, "r") as handle:
            fd = -1
            return json.load(handle)
    except (ValueError, OSError):
        raise AppError("CREDENTIAL_STORAGE_INVALID", "Credential file could not be read.") from None
    finally:
        if fd >= 0:
            os.close(fd)


class FileCredentialStore:
    def __init__(self, directory: Path):
        # Constructor has no side effects, so fixture/live UI boot never creates credentials.
        self.directory = directory

    def _path(self, identifier: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise AppError("INVALID_INPUT", "Invalid account registration identifier.")
        return self.directory / f"{identifier}.json"

    def save(self, record: CredentialRecord) -> str:
        identifier = registration_id(record)
        value = record.model_dump(mode="json")
        for field in ("access_token", "refresh_token", "id_token"):
            token = getattr(record, field)
            value[field] = token.get_secret_value() if token is not None else None
        atomic_json(self._path(identifier), value)
        return identifier

    def load(self, registration: str) -> CredentialRecord:
        try:
            record = CredentialRecord.model_validate(read_protected(self._path(registration)))
        except FileNotFoundError:
            raise AppError("AUTH_REQUIRED", "Connect this ChatGPT account again.") from None
        except ValueError:
            raise AppError("CREDENTIAL_STORAGE_INVALID", "Account record is invalid.") from None
        if registration_id(record) != registration:
            raise AppError("CREDENTIAL_STORAGE_INVALID", "Account registration does not match.")
        return record

    def summaries(self) -> list[AccountSummary]:
        if not self.directory.exists():
            return []
        summaries = []
        for path in sorted(self.directory.glob("*.json")):
            if not re.fullmatch(r"[0-9a-f]{64}", path.stem):
                continue
            record = self.load(path.stem)
            summaries.append(
                AccountSummary(
                    registration_id=path.stem,
                    label=record.label,
                    connected=bool(record.access_token),
                )
            )
        return summaries

    def clear_tokens(self, registration: str) -> None:
        record = self.load(registration)
        self.save(
            record.model_copy(
                update={
                    "access_token": None,
                    "refresh_token": None,
                    "id_token": None,
                    "scopes": [],
                    "expires_at": 0,
                }
            )
        )
