"""ChatGPT session upkeep: serialized refresh, account selection and sign-out.

Per https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions and
the errors-and-recovery page (checked 2026-10-12). Tokens never leave the credential
store except as the return value of `access_token` for an outgoing request.
"""

import fcntl
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx

from gridlens.auth.credentials import (
    FileCredentialStore,
    atomic_json,
    protected_directory,
    read_protected,
)
from gridlens.auth.oauth import ISSUER, PLAN_SCOPE, RESOURCE, TOKEN_URL
from gridlens.contracts import DTO, CredentialRecord
from gridlens.db import now
from gridlens.errors import AppError

DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
REFRESH_MARGIN_SECONDS = 300
TERMINAL_REFRESH_ERRORS = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}
REVOKE_ATTEMPTS = 3


class SessionHandle(DTO):
    """Identifies one selection of an account; results from an older handle are stale."""

    registration_id: str
    epoch: int


class SignOutResult(DTO):
    registration_id: str
    remote_revocation_confirmed: bool


def fetch_discovery(transport: httpx.BaseTransport | None = None) -> dict:
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            response = client.get(DISCOVERY_URL)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        raise AppError("AUTH_SERVICE_UNAVAILABLE", "ChatGPT sign-in is unavailable.") from None


class SessionManager:
    def __init__(
        self,
        store: FileCredentialStore,
        *,
        transport: httpx.BaseTransport | None = None,
        discovery_loader: Callable[[], dict] | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.store = store
        self.transport = transport
        self.discovery_loader = discovery_loader or (lambda: fetch_discovery(transport))
        self.clock = clock
        self.sleep = sleep

    # Selection -----------------------------------------------------------------

    def select(self, registration_id: str) -> SessionHandle:
        """Makes a validated, connected registration active; older handles become stale."""
        record = self.store.load(registration_id)
        if not record.refresh_token:
            raise AppError("AUTH_REQUIRED", "Sign in to this ChatGPT account again.")
        with self._lock("active"):
            epoch = self._active().get("epoch", 0) + 1
            self._write_active({"registration_id": registration_id, "epoch": epoch})
        return SessionHandle(registration_id=registration_id, epoch=epoch)

    def current(self) -> SessionHandle | None:
        active = self._active()
        if not active.get("registration_id"):
            return None
        return SessionHandle(registration_id=active["registration_id"], epoch=active["epoch"])

    def is_current(self, handle: SessionHandle) -> bool:
        return self.current() == handle

    def plan_usage_enabled(self, handle: SessionHandle) -> bool:
        return PLAN_SCOPE in self.store.load(handle.registration_id).scopes

    # Tokens --------------------------------------------------------------------

    def access_token(self, handle: SessionHandle) -> str:
        """A valid access token for the current selection, refreshing near expiry."""
        if not self.is_current(handle):
            raise AppError("ACCOUNT_CHANGED", "The selected ChatGPT account changed.")
        record = self.store.load(handle.registration_id)
        if record.access_token and record.expires_at - self.clock() > REFRESH_MARGIN_SECONDS:
            return record.access_token.get_secret_value()
        record = self.refresh(handle.registration_id)
        if not self.is_current(handle):
            raise AppError("ACCOUNT_CHANGED", "The selected ChatGPT account changed.")
        return record.access_token.get_secret_value()

    def refresh_now(self, registration_id: str) -> CredentialRecord:
        """Forces one refresh (explicit checks); normal use goes through `access_token`."""
        return self.refresh(registration_id, force=True)

    def refresh(self, registration_id: str, *, force: bool = False) -> CredentialRecord:
        """Serialized per registration across tabs and processes; rotated set replaced whole."""
        with self._lock(registration_id):
            # Another tab may have refreshed while we waited; never reuse a rotated token.
            record = self.store.load(registration_id)
            fresh = record.expires_at - self.clock() > REFRESH_MARGIN_SECONDS
            if record.access_token and fresh and not force:
                return record
            if not record.refresh_token:
                raise AppError("AUTH_REQUIRED", "Sign in to this ChatGPT account again.")
            form = {
                "grant_type": "refresh_token",
                "client_id": record.client_id,
                "refresh_token": record.refresh_token.get_secret_value(),
                "resource": RESOURCE,
            }
            try:
                with httpx.Client(timeout=20, transport=self.transport) as client:
                    response = client.post(TOKEN_URL, data=form)
            except httpx.HTTPError:
                # Temporary failure: keep credentials, the user is not signed out.
                raise AppError(
                    "AUTH_REFRESH_UNAVAILABLE", "ChatGPT could not be reached.", retryable=True
                ) from None
            body = _json(response)
            if response.status_code != 200:
                error = body.get("error")
                if error in TERMINAL_REFRESH_ERRORS:
                    self.store.clear_tokens(registration_id, keep_id_token=True)
                    raise AppError("AUTH_EXPIRED", "The ChatGPT session ended. Sign in again.")
                if error == "invalid_client":
                    raise AppError("AUTH_CLIENT_INVALID", "This app registration is invalid.")
                raise AppError(
                    "AUTH_REFRESH_UNAVAILABLE", "ChatGPT session refresh failed.", retryable=True
                )
            if any(not body.get(key) for key in ("access_token", "refresh_token", "expires_in")):
                raise AppError("AUTH_REFRESH_UNAVAILABLE", "The refreshed session was incomplete.")
            try:
                expires_at = int(self.clock()) + int(body["expires_in"])
            except (TypeError, ValueError):
                raise AppError(
                    "AUTH_REFRESH_UNAVAILABLE", "The refreshed session was invalid."
                ) from None
            updated = record.model_copy(
                update={
                    "access_token": body["access_token"],
                    "refresh_token": body["refresh_token"],
                    "id_token": body.get("id_token") or record.id_token,
                    "scopes": str(body["scope"]).split() if body.get("scope") else record.scopes,
                    "expires_at": expires_at,
                    "saved_at": now(),
                }
            )
            # Revalidate the complete set before it replaces the old one atomically.
            updated = CredentialRecord.model_validate(updated.model_dump())
            self.store.save(updated)
            return updated

    # Sign-out ------------------------------------------------------------------

    def sign_out(self, registration_id: str) -> SignOutResult:
        """Stops use first, then revokes, then clears tokens; the registration stays."""
        with self._lock("active"):
            active = self._active()
            if active.get("registration_id") == registration_id:
                self._write_active({"registration_id": None, "epoch": active["epoch"] + 1})
        with self._lock(registration_id):
            record = self.store.load(registration_id)
            confirmed = self._revoke(record) if record.refresh_token else True
            self.store.clear_tokens(registration_id)
        return SignOutResult(registration_id=registration_id, remote_revocation_confirmed=confirmed)

    def _revoke(self, record: CredentialRecord) -> bool:
        try:
            endpoint = self.discovery_loader().get("revocation_endpoint", "")
        except AppError:
            return False
        if not isinstance(endpoint, str) or not endpoint.startswith(f"{ISSUER}/"):
            return False
        form = {
            "token": record.refresh_token.get_secret_value(),
            "token_type_hint": "refresh_token",
            "client_id": record.client_id,
        }
        for attempt in range(REVOKE_ATTEMPTS):
            try:
                with httpx.Client(timeout=10, transport=self.transport) as client:
                    response = client.post(endpoint, data=form)
            except httpx.HTTPError:
                response = None
            if response is not None and response.status_code == 200:
                return True
            if response is not None and response.status_code < 500:
                return False  # a definite refusal; retrying will not confirm revocation
            if attempt < REVOKE_ATTEMPTS - 1:
                self.sleep(2**attempt)
        return False

    # Storage helpers -------------------------------------------------------------

    def _active(self) -> dict:
        path = self.store.directory / "active.json"
        if not path.exists():
            return {"registration_id": None, "epoch": 0}
        return read_protected(path)

    def _write_active(self, value: dict) -> None:
        atomic_json(self.store.directory / "active.json", value)

    @contextmanager
    def _lock(self, name: str) -> Iterator[None]:
        protected_directory(self.store.directory)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.store.directory / f".{name[:64]}.lock", flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
