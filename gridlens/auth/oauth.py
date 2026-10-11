"""Sign in with ChatGPT: loopback PKCE login and callback validation.

Protocol per https://developers.openai.com/siwc/token-sharing-open-source/sign-in and the
issuer's discovery document (checked 2026-10-11). Uses only official endpoints; no
cookies, private APIs or shared tokens. Credentials are saved only after every check passes.
"""

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.host import get_or_create_host_id
from gridlens.contracts import DTO, CredentialRecord
from gridlens.db import now
from gridlens.errors import AppError

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
DYNAMIC_CLIENT = "dynamic_agent_client"
AGENT_NAME = "GridLens"
RESOURCE = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"
CALLBACK_PATH = "/auth/callback"
ATTEMPT_SECONDS = 300

JwksLoader = Callable[[], dict]


class LoginResult(DTO):
    registration_id: str
    label: str
    plan_usage_enabled: bool
    new_registration: bool


@dataclass
class LoginAttempt:
    redirect_uri: str
    client_id: str
    authorize_url: str = ""
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(64))
    expires_at: float = field(default_factory=lambda: time.time() + ATTEMPT_SECONDS)
    expected_subject: str | None = None
    consumed: bool = False

    @property
    def challenge(self) -> str:
        digest = hashlib.sha256(self.verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @property
    def new_registration(self) -> bool:
        return self.client_id == DYNAMIC_CLIENT


class CallbackListener:
    """One-shot HTTP listener on 127.0.0.1; started before the browser opens."""

    def __init__(self, port: int = 0):
        self._received = threading.Event()
        self.params: dict[str, str] | None = None
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parts = urlsplit(self.path)
                if parts.path != CALLBACK_PATH:
                    self.send_error(404)
                    return
                if listener.params is None:
                    query = parse_qs(parts.query, keep_blank_values=True)
                    listener.params = {key: values[0] for key, values in query.items()}
                    listener._received.set()
                body = b"GridLens received the sign-in response. You can close this window."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                # Callback URLs carry authorization codes; never log requests.
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}{CALLBACK_PATH}"

    def wait(self, timeout: float) -> dict[str, str] | None:
        return self.params if self._received.wait(timeout) else None

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def fetch_jwks(transport: httpx.BaseTransport | None = None) -> dict:
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            response = client.get(JWKS_URL)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        raise AppError("OAUTH_JWKS_UNAVAILABLE", "The sign-in keys could not be loaded.") from None


class OAuthLogin:
    def __init__(
        self,
        store: FileCredentialStore,
        *,
        transport: httpx.BaseTransport | None = None,
        jwks_loader: JwksLoader | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.store = store
        self.transport = transport
        self.jwks_loader = jwks_loader or (lambda: fetch_jwks(transport))
        self.clock = clock

    def begin(self, redirect_uri: str, registration_id: str | None = None) -> LoginAttempt:
        """Prepares a fresh attempt; the listener must already be running at redirect_uri."""
        parts = urlsplit(redirect_uri)
        if parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.path != CALLBACK_PATH:
            raise AppError("OAUTH_REDIRECT_INVALID", "The callback must be a 127.0.0.1 loopback.")
        params = {"ext_agent_host_id": get_or_create_host_id(self.store.directory)}
        if registration_id:
            record = self.store.load(registration_id)
            attempt = LoginAttempt(redirect_uri, record.client_id, expected_subject=record.subject)
            if record.id_token:
                params["id_token_hint"] = record.id_token.get_secret_value()
            if record.email:
                params["login_hint"] = record.email
        else:
            attempt = LoginAttempt(redirect_uri, DYNAMIC_CLIENT)
            params["agent_name_hint"] = AGENT_NAME
        attempt.expires_at = self.clock() + ATTEMPT_SECONDS
        query = {
            "client_id": attempt.client_id,
            **params,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": attempt.state,
            "nonce": attempt.nonce,
            "code_challenge": attempt.challenge,
            "code_challenge_method": "S256",
        }
        attempt.authorize_url = f"{AUTHORIZE_URL}?{urlencode(query)}"
        return attempt

    def complete(self, attempt: LoginAttempt, callback: dict[str, str]) -> LoginResult:
        # Single use: any callback, valid or not, ends this attempt.
        if attempt.consumed:
            raise AppError("OAUTH_ATTEMPT_USED", "This sign-in attempt was already used.")
        attempt.consumed = True
        if self.clock() > attempt.expires_at:
            raise AppError("OAUTH_ATTEMPT_EXPIRED", "The sign-in attempt expired. Start again.")
        if not hmac.compare_digest(callback.get("state", ""), attempt.state):
            raise AppError("OAUTH_STATE_MISMATCH", "The sign-in response did not match.")
        if error := callback.get("error"):
            if error == "access_denied":
                raise AppError("OAUTH_ACCESS_DENIED", "ChatGPT access was not authorized.")
            raise AppError("OAUTH_CALLBACK_ERROR", "ChatGPT returned a sign-in error.")
        code = callback.get("code", "")
        if not code:
            raise AppError("OAUTH_CALLBACK_ERROR", "The sign-in response had no code.")
        client_id = self._issued_client(attempt, callback.get("client_id"))
        tokens = self._exchange(attempt, client_id, code)
        claims = self._verify_id_token(tokens["id_token"], client_id, attempt.nonce)
        if attempt.expected_subject and claims["sub"] != attempt.expected_subject:
            raise AppError("OAUTH_ACCOUNT_MISMATCH", "A different ChatGPT account signed in.")
        scopes = str(tokens.get("scope", "")).split()
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        record = CredentialRecord(
            subject=claims["sub"],
            client_id=client_id,
            ext_agent_host_id=get_or_create_host_id(self.store.directory),
            label=email or "ChatGPT account",
            email=email,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            id_token=tokens["id_token"],
            scopes=scopes,
            expires_at=int(self.clock()) + int(tokens["expires_in"]),
            saved_at=now(),
        )
        registration = self.store.save(record)
        return LoginResult(
            registration_id=registration,
            label=record.label,
            # Official guidance: keep the sign-in, but plan usage stays off without this scope.
            plan_usage_enabled=PLAN_SCOPE in scopes,
            new_registration=attempt.new_registration,
        )

    @staticmethod
    def _issued_client(attempt: LoginAttempt, returned: str | None) -> str:
        if attempt.new_registration:
            if not returned or returned == DYNAMIC_CLIENT:
                raise AppError(
                    "OAUTH_REGISTRATION_INCOMPLETE", "ChatGPT did not issue a client ID."
                )
            return returned
        if returned and returned != attempt.client_id:
            raise AppError("OAUTH_CLIENT_MISMATCH", "The sign-in response used another client.")
        return attempt.client_id

    def _exchange(self, attempt: LoginAttempt, client_id: str, code: str) -> dict:
        form = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": attempt.verifier,
            "redirect_uri": attempt.redirect_uri,
            "resource": RESOURCE,
        }
        try:
            with httpx.Client(timeout=20, transport=self.transport) as client:
                response = client.post(TOKEN_URL, data=form)
        except httpx.HTTPError:
            raise AppError(
                "OAUTH_EXCHANGE_FAILED", "The sign-in could not be completed.", retryable=True
            ) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200:
            if isinstance(body, dict) and body.get("error") == "invalid_grant":
                raise AppError("OAUTH_INVALID_GRANT", "The sign-in code expired. Start again.")
            raise AppError("OAUTH_EXCHANGE_FAILED", "The sign-in could not be completed.")
        required = ("access_token", "refresh_token", "id_token", "expires_in")
        if not isinstance(body, dict) or any(not body.get(key) for key in required):
            raise AppError("OAUTH_EXCHANGE_FAILED", "The sign-in response was incomplete.")
        try:
            int(body["expires_in"])
        except (TypeError, ValueError):
            raise AppError("OAUTH_EXCHANGE_FAILED", "The sign-in response was invalid.") from None
        return body

    def _verify_id_token(self, id_token: str, client_id: str, nonce: str) -> dict:
        try:
            header = jwt.get_unverified_header(id_token)
            keys = jwt.PyJWKSet.from_dict(self.jwks_loader())
            key = next(k for k in keys.keys if k.key_id == header.get("kid"))
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=ISSUER,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except AppError:
            raise
        except (jwt.PyJWTError, StopIteration, ValueError, KeyError):
            raise AppError("OAUTH_ID_TOKEN_INVALID", "The sign-in identity was invalid.") from None
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise AppError("OAUTH_ID_TOKEN_INVALID", "The sign-in identity was invalid.")
        return claims


def run_browser_login(
    login: OAuthLogin,
    *,
    registration_id: str | None = None,
    timeout: float = ATTEMPT_SECONDS,
    open_browser: Callable[[str], object] | None = None,
) -> LoginResult:
    """Starts the listener first, opens the official page, and always closes the listener."""
    if open_browser is None:
        import webbrowser

        open_browser = webbrowser.open
    listener = CallbackListener()
    try:
        attempt = login.begin(listener.redirect_uri, registration_id)
        open_browser(attempt.authorize_url)
        callback = listener.wait(timeout)
        if callback is None:
            raise AppError("OAUTH_TIMEOUT", "Sign-in timed out. Start again.")
        return login.complete(attempt, callback)
    finally:
        listener.close()
