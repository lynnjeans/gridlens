import base64
import hashlib
import json
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.oauth import (
    DYNAMIC_CLIENT,
    ISSUER,
    PLAN_SCOPE,
    RESOURCE,
    SCOPES,
    TOKEN_URL,
    OAuthLogin,
    run_browser_login,
)
from gridlens.errors import AppError

ISSUED = "oaiapp_synthetic_issued"
REDIRECT = "http://127.0.0.1:1455/auth/callback"
SUBJECT = "synthetic-subject"


def keypair(kid="test-key"):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    return private, {"keys": [{**public, "kid": kid, "alg": "RS256", "use": "sig"}]}


PRIVATE, JWKS = keypair()
OTHER_PRIVATE, _ = keypair()


def id_token(
    nonce, *, aud=ISSUED, iss=ISSUER, sub=SUBJECT, exp_offset=3600, key=PRIVATE, kid="test-key"
):
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "nonce": nonce,
        "email": "user@example.test",
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


class TokenEndpoint:
    def __init__(self):
        self.requests = []
        self.response = None

    def __call__(self, request: httpx.Request):
        assert str(request.url) == TOKEN_URL
        self.requests.append(dict(parse_qs(request.content.decode())))
        status, body = self.response
        return httpx.Response(status, json=body)

    def tokens(self, nonce, scope=SCOPES, **claims):
        self.response = (
            200,
            {
                "access_token": "synthetic-access",
                "refresh_token": "synthetic-refresh",
                "id_token": id_token(nonce, **claims),
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": scope,
            },
        )


@pytest.fixture
def setup(tmp_path):
    store = FileCredentialStore(tmp_path / "auth")
    endpoint = TokenEndpoint()
    clock = {"now": 1_000_000.0}
    login = OAuthLogin(
        store,
        transport=httpx.MockTransport(endpoint),
        jwks_loader=lambda: JWKS,
        clock=lambda: clock["now"],
    )
    return login, store, endpoint, clock


def query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def callback(attempt, **extra):
    return {"code": "synthetic-code", "state": attempt.state, "client_id": ISSUED, **extra}


def test_first_registration_authorize_url(setup):
    login, store, _, _ = setup
    attempt = login.begin(REDIRECT)
    params = query(attempt.authorize_url)
    assert attempt.authorize_url.startswith("https://auth.openai.com/api/accounts/authorize?")
    assert params["client_id"] == DYNAMIC_CLIENT
    assert params["agent_name_hint"] == "GridLens"
    assert params["ext_agent_host_id"].startswith("urn:uuid:")
    assert params["scope"] == SCOPES and PLAN_SCOPE in params["scope"].split()
    assert params["resource"] == RESOURCE and params["response_type"] == "code"
    assert params["redirect_uri"] == REDIRECT
    assert params["code_challenge_method"] == "S256"
    digest = hashlib.sha256(attempt.verifier.encode()).digest()
    assert params["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert "id_token_hint" not in params and "login_hint" not in params
    other = login.begin(REDIRECT)
    assert {other.state, other.nonce, other.verifier}.isdisjoint(
        {attempt.state, attempt.nonce, attempt.verifier}
    )


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost:1455/auth/callback",
        "https://127.0.0.1:1455/auth/callback",
        "http://127.0.0.1:1455/callback",
    ],
)
def test_redirect_must_be_exact_loopback(setup, uri):
    login, *_ = setup
    with pytest.raises(AppError) as raised:
        login.begin(uri)
    assert raised.value.code == "OAUTH_REDIRECT_INVALID"


def test_successful_registration_saves_issued_client_only_after_checks(setup):
    login, store, endpoint, _ = setup
    attempt = login.begin(REDIRECT)
    endpoint.tokens(attempt.nonce)
    result = login.complete(attempt, callback(attempt))
    assert result.plan_usage_enabled and result.new_registration
    [form] = endpoint.requests
    assert form == {
        "grant_type": ["authorization_code"],
        "client_id": [ISSUED],
        "code": ["synthetic-code"],
        "code_verifier": [attempt.verifier],
        "redirect_uri": [REDIRECT],
        "resource": [RESOURCE],
    }
    record = store.load(result.registration_id)
    assert record.client_id == ISSUED and record.subject == SUBJECT
    assert record.expires_at == 1_000_000 + 3600
    assert PLAN_SCOPE in record.scopes
    assert "synthetic-access" not in repr(result) and "synthetic-access" not in repr(record)


def assert_rejected(login, store, endpoint, attempt, params, code, *, exchanged=False):
    with pytest.raises(AppError) as raised:
        login.complete(attempt, params)
    assert raised.value.code == code
    assert bool(endpoint.requests) == exchanged
    assert store.summaries() == []


def test_wrong_state_and_denied_access_never_exchange(setup):
    login, store, endpoint, _ = setup
    attempt = login.begin(REDIRECT)
    assert_rejected(
        login, store, endpoint, attempt, callback(attempt, state="forged"), "OAUTH_STATE_MISMATCH"
    )
    denied = login.begin(REDIRECT)
    assert_rejected(
        login,
        store,
        endpoint,
        denied,
        {"state": denied.state, "error": "access_denied"},
        "OAUTH_ACCESS_DENIED",
    )
    other = login.begin(REDIRECT)
    assert_rejected(
        login,
        store,
        endpoint,
        other,
        {"state": other.state, "error": "server_error"},
        "OAUTH_CALLBACK_ERROR",
    )


@pytest.mark.parametrize("returned", [None, DYNAMIC_CLIENT])
def test_registration_without_issued_client_is_incomplete(setup, returned):
    login, store, endpoint, _ = setup
    attempt = login.begin(REDIRECT)
    params = callback(attempt)
    params.pop("client_id")
    if returned:
        params["client_id"] = returned
    assert_rejected(login, store, endpoint, attempt, params, "OAUTH_REGISTRATION_INCOMPLETE")


def test_repeated_and_expired_callbacks_are_rejected(setup):
    login, store, endpoint, clock = setup
    attempt = login.begin(REDIRECT)
    endpoint.tokens(attempt.nonce)
    login.complete(attempt, callback(attempt))
    with pytest.raises(AppError) as raised:
        login.complete(attempt, callback(attempt))
    assert raised.value.code == "OAUTH_ATTEMPT_USED"
    assert len(endpoint.requests) == 1

    expired = login.begin(REDIRECT)
    clock["now"] += 301
    with pytest.raises(AppError) as raised:
        login.complete(expired, callback(expired))
    assert raised.value.code == "OAUTH_ATTEMPT_EXPIRED"
    assert len(endpoint.requests) == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "other-nonce"},
        {"aud": "oaiapp_other"},
        {"aud": DYNAMIC_CLIENT},
        {"iss": "https://evil.example"},
        {"exp_offset": -10},
        {"key": OTHER_PRIVATE},
        {"kid": "unknown-key"},
    ],
)
def test_invalid_id_tokens_are_rejected(setup, claims):
    login, store, endpoint, _ = setup
    attempt = login.begin(REDIRECT)
    nonce = claims.pop("nonce", attempt.nonce)
    endpoint.tokens(nonce, **claims)
    assert_rejected(
        login, store, endpoint, attempt, callback(attempt), "OAUTH_ID_TOKEN_INVALID", exchanged=True
    )


def test_missing_plan_scope_keeps_sign_in_but_disables_plan_usage(setup):
    login, store, endpoint, _ = setup
    attempt = login.begin(REDIRECT)
    endpoint.tokens(attempt.nonce, scope="openid profile email offline_access")
    result = login.complete(attempt, callback(attempt))
    assert not result.plan_usage_enabled
    assert PLAN_SCOPE not in store.load(result.registration_id).scopes


def test_exchange_errors_save_nothing(setup):
    login, store, endpoint, _ = setup
    attempt = login.begin(REDIRECT)
    endpoint.response = (400, {"error": "invalid_grant"})
    assert_rejected(
        login, store, endpoint, attempt, callback(attempt), "OAUTH_INVALID_GRANT", exchanged=True
    )
    partial = login.begin(REDIRECT)
    endpoint.requests.clear()
    endpoint.response = (200, {"access_token": "a", "id_token": "b", "expires_in": 3600})
    assert_rejected(
        login, store, endpoint, partial, callback(partial), "OAUTH_EXCHANGE_FAILED", exchanged=True
    )


def test_returning_sign_in_reuses_issued_client_and_checks_identity(setup):
    login, store, endpoint, _ = setup
    first = login.begin(REDIRECT)
    endpoint.tokens(first.nonce)
    registration = login.complete(first, callback(first)).registration_id
    saved = store.load(registration)

    again = login.begin(REDIRECT, registration)
    params = query(again.authorize_url)
    assert params["client_id"] == ISSUED and "agent_name_hint" not in params
    assert params["id_token_hint"] == saved.id_token.get_secret_value()
    assert params["login_hint"] == "user@example.test"
    assert params["ext_agent_host_id"] == saved.ext_agent_host_id

    with pytest.raises(AppError) as raised:
        login.complete(again, callback(again, client_id="oaiapp_other"))
    assert raised.value.code == "OAUTH_CLIENT_MISMATCH"

    other = login.begin(REDIRECT, registration)
    endpoint.tokens(other.nonce, sub="another-subject")
    no_client = callback(other)
    no_client.pop("client_id")
    with pytest.raises(AppError) as raised:
        login.complete(other, no_client)
    assert raised.value.code == "OAUTH_ACCOUNT_MISMATCH"
    assert store.load(registration).id_token == saved.id_token
    assert len(store.summaries()) == 1


def test_synthetic_fixture_token_verifies_against_fixture_jwks(setup, fixtures_dir):
    oauth = json.loads((fixtures_dir / "scenarios.json").read_text())["oauth"]
    login = OAuthLogin(setup[1], jwks_loader=lambda: oauth["jwks"])
    claims = login._verify_id_token(oauth["id_token"], oauth["client_id"], oauth["nonce"])
    assert claims["sub"] == "synthetic-subject"
    with pytest.raises(AppError):
        login._verify_id_token(oauth["id_token"], oauth["client_id"], "wrong-nonce")


@pytest.mark.enable_socket
@pytest.mark.allow_hosts(["127.0.0.1"])
def test_listener_lifecycle_success_and_timeout(setup):
    """Loopback only: the listener starts before the browser and always closes."""
    login, store, endpoint, _ = setup
    ports = []

    def browser(url):
        params = query(url)
        redirect = params["redirect_uri"]
        ports.append(urlsplit(redirect).port)
        endpoint.tokens(params["nonce"])

        def hit():
            httpx.get(redirect, params={"code": "c", "state": params["state"], "client_id": ISSUED})

        threading.Thread(target=hit).start()

    result = run_browser_login(login, timeout=5, open_browser=browser)
    assert result.plan_usage_enabled
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", ports[0]), timeout=1)

    with pytest.raises(AppError) as raised:
        run_browser_login(
            login,
            timeout=0.2,
            open_browser=lambda url: ports.append(urlsplit(query(url)["redirect_uri"]).port),
        )
    assert raised.value.code == "OAUTH_TIMEOUT"
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", ports[-1]), timeout=1)
    assert len(store.summaries()) == 1


def test_cli_login_refuses_fixture_mode(monkeypatch, capsys):
    from gridlens import cli
    from gridlens.config import Settings

    with pytest.raises(SystemExit):
        cli._login(Settings(), None)
    assert "APP_MODE=live" in capsys.readouterr().err
