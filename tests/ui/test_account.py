import json

from streamlit.testing.v1 import AppTest

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.oauth import SCOPES
from gridlens.auth.sessions import SessionManager
from gridlens.contracts import CredentialRecord

FAR_FUTURE = 4_000_000_000


def seed(tmp_path, subject, *, scopes=SCOPES):
    store = FileCredentialStore(tmp_path / "auth")
    return store.save(
        CredentialRecord(
            subject=subject,
            client_id=f"oaiapp_{subject}",
            ext_agent_host_id="urn:uuid:host",
            label=f"{subject}@example.test",
            access_token=f"token-{subject}",
            refresh_token=f"r-{subject}",
            id_token="id",
            scopes=scopes.split(),
            expires_at=FAR_FUTURE,
            saved_at="2026-10-12T00:00:00+00:00",
        )
    )


def account_app(tmp_path, mode="live"):
    log = tmp_path / "requests.json"
    script = f"""
import json, httpx
from pathlib import Path
import streamlit as st
from gridlens.config import Settings
from gridlens.bootstrap import build_container
from gridlens.ui.account import render_account, selected_model

root = Path({str(tmp_path)!r})
extra = {{"auth_dir": root / "auth"}} if {mode!r} == "live" else {{}}
settings = Settings(project_root=root / "app", mode={mode!r}, **extra)
c = build_container(settings)
log = Path({str(log)!r})

def handler(request):
    seen = json.loads(log.read_text()) if log.exists() else []
    seen.append(request.headers["Authorization"])
    log.write_text(json.dumps(seen))
    who = request.headers["Authorization"].split("-")[-1]
    return httpx.Response(200, json={{"models": [
        {{"slug": f"model-{{who}}", "display_name": f"Model for {{who}}", "visibility": "list"}}
    ]}})

c.catalog.transport = httpx.MockTransport(handler)
render_account(c)
choice = selected_model(c)
st.session_state["test_choice"] = [choice[0].registration_id, choice[1]] if choice else None
"""
    return AppTest.from_string(script).run(), log


def requests(log):
    return json.loads(log.read_text()) if log.exists() else []


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_fixture_mode_shows_disabled_sign_in(tmp_path):
    app, _ = account_app(tmp_path, mode="fixture")
    assert not app.exception
    assert button(app, "Continue with ChatGPT").disabled


def test_live_without_accounts_offers_sign_in(tmp_path):
    app, log = account_app(tmp_path)
    assert not app.exception
    assert not button(app, "Continue with ChatGPT").disabled
    assert requests(log) == []


def test_catalog_loads_once_per_account_and_switching_resets_choice(tmp_path):
    a = seed(tmp_path, "a")
    b = seed(tmp_path, "b")
    SessionManager(FileCredentialStore(tmp_path / "auth")).select(a)
    app, log = account_app(tmp_path)
    assert not app.exception
    assert requests(log) == ["Bearer token-a"]
    model = app.selectbox(key=f"account_model_picker_{a}:1")
    assert model.options == ["Model for a"]
    model.set_value("model-a").run()
    assert app.session_state["test_choice"] == [a, "model-a"]
    app.run()
    app.run()
    assert requests(log) == ["Bearer token-a"]  # reruns never refetch

    app.selectbox(key=f"account_picker_{a}").set_value(b).run()
    assert not app.exception
    assert requests(log) == ["Bearer token-a", "Bearer token-b"]
    assert app.session_state["test_choice"] is None  # old model never carried over
    assert app.selectbox(key=f"account_model_picker_{b}:2").options == ["Model for b"]
    page = str([e.value for e in app.markdown] + [e.value for e in app.caption])
    assert "token-a" not in page and "token-b" not in page


def test_chosen_model_is_restored_in_a_new_session(tmp_path):
    a = seed(tmp_path, "a")
    b = seed(tmp_path, "b")
    SessionManager(FileCredentialStore(tmp_path / "auth")).select(a)
    app, _ = account_app(tmp_path)
    app.selectbox(key=f"account_model_picker_{a}:1").set_value("model-a").run()

    restarted, _ = account_app(tmp_path)  # a fresh session, as after an app restart
    assert not restarted.exception
    assert restarted.session_state["test_choice"] == [a, "model-a"]

    SessionManager(FileCredentialStore(tmp_path / "auth")).select(b)
    other, _ = account_app(tmp_path)
    assert other.session_state["test_choice"] is None  # never borrowed from another account


def test_missing_plan_scope_disables_models(tmp_path):
    a = seed(tmp_path, "a", scopes="openid profile email offline_access")
    SessionManager(FileCredentialStore(tmp_path / "auth")).select(a)
    app, log = account_app(tmp_path)
    assert any("not granted ChatGPT plan usage" in w.value for w in app.warning)
    assert requests(log) == []
    assert app.session_state["test_choice"] is None
    assert any(b.label == "Reauthorize" for b in app.button)


def test_sign_out_clears_tokens_and_returns_to_sign_in(tmp_path, monkeypatch):
    a = seed(tmp_path, "a")
    SessionManager(FileCredentialStore(tmp_path / "auth")).select(a)
    # Simulate an unreachable revocation endpoint; tokens must still be cleared.
    monkeypatch.setattr(SessionManager, "_revoke", lambda self, record: False)
    app, _ = account_app(tmp_path)
    button(app, "Sign out").click().run()
    assert not app.exception
    assert FileCredentialStore(tmp_path / "auth").load(a).refresh_token is None
    assert any("Remote revocation was not confirmed" in s.value for s in app.success)
    assert any(b.label == "Continue with ChatGPT" for b in app.button)
