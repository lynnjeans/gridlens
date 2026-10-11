import httpx
import pytest

from gridlens.auth.catalog import MODELS_URL, ModelCatalog
from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.oauth import SCOPES
from gridlens.auth.sessions import SessionManager
from gridlens.contracts import CredentialRecord, ModelChoice
from gridlens.errors import AppError

NOW = 1_000_000.0


def save(store, subject, client, access):
    return store.save(
        CredentialRecord(
            subject=subject,
            client_id=client,
            ext_agent_host_id="urn:uuid:host",
            label=subject,
            access_token=access,
            refresh_token=f"r-{subject}",
            id_token="id",
            scopes=SCOPES.split(),
            expires_at=int(NOW) + 3600,
            saved_at="2026-10-12T00:00:00+00:00",
        )
    )


@pytest.fixture
def env(tmp_path):
    store = FileCredentialStore(tmp_path / "auth")
    sessions = SessionManager(store, clock=lambda: NOW)
    requests = []
    responses = {}

    def handler(request):
        assert str(request.url) == MODELS_URL and request.method == "GET"
        requests.append(request.headers["Authorization"])
        return responses.get("next") or httpx.Response(200, json={"models": []})

    catalog = ModelCatalog(sessions, transport=httpx.MockTransport(handler))
    a, b = save(store, "a", "oaiapp_a", "token-a"), save(store, "b", "oaiapp_b", "token-b")
    return sessions, catalog, requests, responses, a, b


def test_lists_only_listed_models_in_server_order_with_bearer(env):
    sessions, catalog, requests, responses, a, _ = env
    responses["next"] = httpx.Response(
        200,
        json={
            "models": [
                {"slug": "model-z", "display_name": "Model Z", "visibility": "list"},
                {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
                {"slug": "model-a", "visibility": "list"},
                {"slug": "model-z", "display_name": "Duplicate", "visibility": "list"},
                {"display_name": "No slug", "visibility": "list"},
                "garbage",
            ]
        },
    )
    choices = catalog.fetch(sessions.select(a))
    assert choices == [
        ModelChoice(slug="model-z", display_name="Model Z"),
        ModelChoice(slug="model-a", display_name="model-a"),
    ]
    assert requests == ["Bearer token-a"]


def test_empty_catalog_is_an_empty_choice_list(env):
    sessions, catalog, _, _, a, _ = env
    assert catalog.fetch(sessions.select(a)) == []


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTH_EXPIRED"),
        (403, "PLAN_PERMISSION_MISSING"),
        (429, "USAGE_LIMITED"),
        (503, "MODEL_CATALOG_UNAVAILABLE"),
    ],
)
def test_errors_are_distinct(env, status, code):
    sessions, catalog, _, responses, a, _ = env
    responses["next"] = httpx.Response(status, json={})
    with pytest.raises(AppError) as raised:
        catalog.fetch(sessions.select(a))
    assert raised.value.code == code


def test_malformed_catalog_is_rejected(env):
    sessions, catalog, _, responses, a, _ = env
    responses["next"] = httpx.Response(200, json={"data": []})
    with pytest.raises(AppError) as raised:
        catalog.fetch(sessions.select(a))
    assert raised.value.code == "MODEL_CATALOG_UNAVAILABLE"


def test_catalog_for_a_stale_selection_is_discarded(env):
    sessions, catalog, requests, responses, a, b = env
    first = sessions.select(a)
    sessions.select(b)
    with pytest.raises(AppError) as raised:
        catalog.fetch(first)
    assert raised.value.code == "ACCOUNT_CHANGED"
    assert requests == []

    handle = sessions.select(a)

    def switch_then_answer(request):
        sessions.select(b)
        return httpx.Response(200, json={"models": [{"slug": "m", "visibility": "list"}]})

    catalog.transport = httpx.MockTransport(switch_then_answer)
    with pytest.raises(AppError) as raised:
        catalog.fetch(handle)
    assert raised.value.code == "ACCOUNT_CHANGED"
