"""Real session refresh (and optional sign-out) for an account signed in with `gridlens login`.

    APP_MODE=live GRIDLENS_LIVE_SESSION=1 .venv/bin/python -m pytest -m live -k live_sessions -s
    Add GRIDLENS_LIVE_SIGNOUT=1 to also revoke and clear that account's tokens.

Prints only redacted results.
"""

import os

import pytest

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.sessions import SessionManager
from gridlens.config import Settings


@pytest.mark.live
@pytest.mark.enable_socket
def test_real_refresh_and_optional_sign_out():
    if os.environ.get("GRIDLENS_LIVE_SESSION") != "1":
        pytest.skip("Set GRIDLENS_LIVE_SESSION=1 to refresh a real signed-in account")
    settings = Settings.from_env()
    if settings.mode != "live":
        pytest.skip("Real sessions require APP_MODE=live")
    store = FileCredentialStore(settings.auth_dir)
    connected = [s for s in store.summaries() if s.connected]
    if not connected:
        pytest.skip("No signed-in account; run `gridlens login` first")
    sessions = SessionManager(store)
    registration = connected[0].registration_id
    before = store.load(registration).expires_at
    after = sessions.refresh_now(registration)
    assert after.expires_at >= before and after.refresh_token
    plan = sessions.plan_usage_enabled(sessions.select(registration))
    print(f"refreshed registration={registration[:12]}… plan_usage={plan}")
    if os.environ.get("GRIDLENS_LIVE_SIGNOUT") == "1":
        result = sessions.sign_out(registration)
        assert store.load(registration).refresh_token is None
        print(f"signed out; remote revocation confirmed={result.remote_revocation_confirmed}")
