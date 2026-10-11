"""Real Sign in with ChatGPT. The account owner completes the official page themselves.

    APP_MODE=live GRIDLENS_LIVE_LOGIN=1 .venv/bin/python -m pytest -m live -k login -s

Records only redacted results; tokens are never printed.
"""

import os

import pytest

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.oauth import PLAN_SCOPE, OAuthLogin, run_browser_login
from gridlens.config import Settings


@pytest.mark.live
@pytest.mark.enable_socket
def test_real_browser_login_grants_plan_usage():
    if os.environ.get("GRIDLENS_LIVE_LOGIN") != "1":
        pytest.skip("Set GRIDLENS_LIVE_LOGIN=1 to run an interactive real sign-in")
    settings = Settings.from_env()
    if settings.mode != "live":
        pytest.skip("Real sign-in requires APP_MODE=live")
    store = FileCredentialStore(settings.auth_dir)
    result = run_browser_login(OAuthLogin(store), timeout=300)
    record = store.load(result.registration_id)
    assert record.client_id != "dynamic_agent_client"
    print(
        f"registration={result.registration_id[:12]}… new={result.new_registration} "
        f"plan_scope={PLAN_SCOPE in record.scopes} scopes={sorted(record.scopes)}"
    )
    assert result.plan_usage_enabled
