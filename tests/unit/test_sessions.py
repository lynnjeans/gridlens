import threading
import time
from urllib.parse import parse_qs

import httpx
import pytest

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.oauth import PLAN_SCOPE, RESOURCE, SCOPES, TOKEN_URL
from gridlens.auth.sessions import SessionManager
from gridlens.contracts import CredentialRecord
from gridlens.errors import AppError

REVOKE_URL = "https://auth.openai.com/api/accounts/oauth/revoke"
NOW = 1_000_000.0


def record(subject, client_id, *, refresh="r1", access="a1", expires_in=3600):
    return CredentialRecord(
        subject=subject,
        client_id=client_id,
        ext_agent_host_id="urn:uuid:00000000-0000-4000-8000-000000000001",
        label=f"{subject}@example.test",
        email=f"{subject}@example.test",
        access_token=access,
        refresh_token=refresh,
        id_token=f"id-{subject}",
        scopes=SCOPES.split(),
        expires_at=int(NOW) + expires_in,
        saved_at="2026-10-12T00:00:00+00:00",
    )


class AuthServer:
    """Token + revocation endpoints with real refresh-token rotation semantics."""

    def __init__(self):
        self.valid_refresh = {"oaiapp_a": "r1", "oaiapp_b": "rb"}
        self.refresh_calls = []
        self.revoke_calls = []
        self.refresh_status = None  # (status, body) override
        self.revoke_responses = []
        self.delay = 0.0
        self.lock = threading.Lock()

    def __call__(self, request: httpx.Request):
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if str(request.url) == TOKEN_URL:
            return self._refresh(form)
        if str(request.url) == REVOKE_URL:
            self.revoke_calls.append(form)
            response = self.revoke_responses.pop(0) if self.revoke_responses else 200
            if isinstance(response, Exception):
                raise response
            return httpx.Response(response)
        raise AssertionError(f"unexpected request to {request.url}")

    def _refresh(self, form):
        time.sleep(self.delay)
        with self.lock:
            self.refresh_calls.append(form)
            if self.refresh_status:
                status, body = self.refresh_status
                return httpx.Response(status, json=body)
            client = form["client_id"]
            if form["refresh_token"] != self.valid_refresh[client]:
                return httpx.Response(400, json={"error": "refresh_token_reused"})
            generation = len(self.refresh_calls)
            self.valid_refresh[client] = f"r{generation + 1}-{client}"
            return httpx.Response(
                200,
                json={
                    "access_token": f"a{generation + 1}-{client}",
                    "refresh_token": self.valid_refresh[client],
                    "id_token": f"id{generation + 1}",
                    "expires_in": 3600,
                    "scope": SCOPES,
                    "token_type": "Bearer",
                },
            )


@pytest.fixture
def env(tmp_path):
    store = FileCredentialStore(tmp_path / "auth")
    server = AuthServer()
    clock = {"now": NOW}
    sleeps = []
    sessions = SessionManager(
        store,
        transport=httpx.MockTransport(server),
        discovery_loader=lambda: {"revocation_endpoint": REVOKE_URL},
        clock=lambda: clock["now"],
        sleep=sleeps.append,
    )
    a = store.save(record("a", "oaiapp_a"))
    b = store.save(record("b", "oaiapp_b", refresh="rb", access="ab"))
    return sessions, store, server, clock, sleeps, a, b


def test_fresh_token_is_used_without_network(env):
    sessions, _, server, _, _, a, _ = env
    handle = sessions.select(a)
    assert sessions.access_token(handle) == "a1"
    assert server.refresh_calls == []


def test_refresh_near_expiry_replaces_rotated_set(env):
    sessions, store, server, clock, _, a, _ = env
    handle = sessions.select(a)
    clock["now"] = NOW + 3600 - 60
    token = sessions.access_token(handle)
    assert server.refresh_calls == [
        {
            "grant_type": "refresh_token",
            "client_id": "oaiapp_a",
            "refresh_token": "r1",
            "resource": RESOURCE,
        }
    ]
    saved = store.load(a)
    assert token == saved.access_token.get_secret_value()
    assert saved.refresh_token.get_secret_value() == server.valid_refresh["oaiapp_a"]
    assert saved.expires_at == int(clock["now"]) + 3600 and saved.id_token
    clock["now"] += 3600
    sessions.access_token(handle)  # uses the rotated refresh token, not "r1"
    assert server.refresh_calls[-1]["refresh_token"] != "r1"
    assert len(server.refresh_calls) == 2


def test_concurrent_refreshes_do_not_race_the_rotating_token(env):
    sessions, store, server, clock, _, a, _ = env
    handle = sessions.select(a)
    clock["now"] = NOW + 3600
    server.delay = 0.2
    tokens, errors = [], []

    def worker():
        try:
            tokens.append(
                SessionManager(
                    store, transport=httpx.MockTransport(server), clock=lambda: clock["now"]
                ).access_token(handle)
            )
        except AppError as error:
            errors.append(error.code)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(server.refresh_calls) == 1
    assert len(set(tokens)) == 1


@pytest.mark.parametrize("error", ["invalid_grant", "refresh_token_reused", "token_expired"])
def test_terminal_refresh_error_requires_sign_in_and_isolates_accounts(env, error):
    sessions, store, server, clock, _, a, b = env
    handle = sessions.select(a)
    clock["now"] = NOW + 3600
    server.refresh_status = (400, {"error": error})
    with pytest.raises(AppError) as raised:
        sessions.access_token(handle)
    assert raised.value.code == "AUTH_EXPIRED"
    cleared = store.load(a)
    assert cleared.access_token is None and cleared.refresh_token is None
    assert cleared.id_token is not None  # kept only as a sign-in hint
    assert cleared.client_id == "oaiapp_a"
    other = store.load(b)
    assert other.refresh_token.get_secret_value() == "rb"


@pytest.mark.parametrize(
    "status_body,code,cleared",
    [
        ((503, {}), "AUTH_REFRESH_UNAVAILABLE", False),
        ((400, {"error": "invalid_client"}), "AUTH_CLIENT_INVALID", False),
        ((200, {"access_token": "x", "expires_in": 3600}), "AUTH_REFRESH_UNAVAILABLE", False),
    ],
)
def test_temporary_or_incomplete_refresh_keeps_old_credentials(env, status_body, code, cleared):
    sessions, store, server, clock, _, a, _ = env
    handle = sessions.select(a)
    clock["now"] = NOW + 3600
    server.refresh_status = status_body
    with pytest.raises(AppError) as raised:
        sessions.access_token(handle)
    assert raised.value.code == code
    kept = store.load(a)
    assert kept.refresh_token.get_secret_value() == "r1"
    assert kept.access_token.get_secret_value() == "a1"


def test_network_failure_during_refresh_keeps_credentials(env, monkeypatch):
    sessions, store, server, clock, _, a, _ = env
    handle = sessions.select(a)
    clock["now"] = NOW + 3600

    def broken(request):
        raise httpx.ConnectError("offline")

    sessions.transport = httpx.MockTransport(broken)
    with pytest.raises(AppError) as raised:
        sessions.access_token(handle)
    assert raised.value.code == "AUTH_REFRESH_UNAVAILABLE" and raised.value.retryable
    assert store.load(a).refresh_token.get_secret_value() == "r1"


def test_switching_accounts_never_mixes_tokens(env):
    sessions, _, _, _, _, a, b = env
    first = sessions.select(a)
    second = sessions.select(b)
    assert second.epoch == first.epoch + 1
    assert sessions.access_token(second) == "ab"
    with pytest.raises(AppError) as raised:
        sessions.access_token(first)
    assert raised.value.code == "ACCOUNT_CHANGED"
    assert not sessions.is_current(first) and sessions.is_current(second)
    assert sessions.plan_usage_enabled(second) is (PLAN_SCOPE in SCOPES.split())


def test_signed_out_registration_cannot_be_selected(env):
    sessions, _, _, _, _, a, _ = env
    sessions.sign_out(a)
    with pytest.raises(AppError) as raised:
        sessions.select(a)
    assert raised.value.code == "AUTH_REQUIRED"


def test_sign_out_revokes_then_clears_and_keeps_registration(env):
    sessions, store, server, _, _, a, b = env
    handle = sessions.select(a)
    result = sessions.sign_out(a)
    assert result.remote_revocation_confirmed
    assert server.revoke_calls == [
        {"token": "r1", "token_type_hint": "refresh_token", "client_id": "oaiapp_a"}
    ]
    signed_out = store.load(a)
    assert (signed_out.access_token, signed_out.refresh_token, signed_out.id_token) == (
        None,
        None,
        None,
    )
    assert signed_out.client_id == "oaiapp_a" and signed_out.ext_agent_host_id
    assert sessions.current() is None
    with pytest.raises(AppError) as raised:
        sessions.access_token(handle)
    assert raised.value.code == "ACCOUNT_CHANGED"
    assert store.load(b).refresh_token.get_secret_value() == "rb"


def test_unconfirmed_revocation_still_clears_local_tokens(env):
    sessions, store, server, _, sleeps, a, _ = env
    server.revoke_responses = [httpx.ConnectError("down"), 503, 502]
    result = sessions.sign_out(a)
    assert not result.remote_revocation_confirmed
    assert len(server.revoke_calls) == 3 and sleeps == [1, 2]
    assert store.load(a).refresh_token is None


def test_definite_refusal_is_not_retried(env):
    sessions, _, server, _, sleeps, a, _ = env
    server.revoke_responses = [400]
    assert not sessions.sign_out(a).remote_revocation_confirmed
    assert len(server.revoke_calls) == 1 and sleeps == []


@pytest.mark.parametrize(
    "loader",
    [
        lambda: (_ for _ in ()).throw(AppError("AUTH_SERVICE_UNAVAILABLE", "down")),
        lambda: {"revocation_endpoint": "https://evil.example/revoke"},
        lambda: {},
    ],
)
def test_unusable_discovery_means_unconfirmed_without_sending_the_token(env, loader):
    sessions, store, server, _, _, a, _ = env
    sessions.discovery_loader = loader
    assert not sessions.sign_out(a).remote_revocation_confirmed
    assert server.revoke_calls == []
    assert store.load(a).refresh_token is None


def test_forced_refresh_and_cli_logout_require_a_known_account(env, capsys):
    sessions, store, server, _, _, a, _ = env
    sessions.refresh_now(a)
    assert len(server.refresh_calls) == 1
    from gridlens import cli
    from gridlens.config import Settings

    with pytest.raises(SystemExit):
        cli._logout(Settings(), None)
    assert "--account" in capsys.readouterr().err
