"""Account-specific model catalog (official `GET /v1/models`, checked 2026-10-12).

Nothing is hard-coded: choices come only from the selected account's catalog, and a
response that arrives after the account changed is discarded.
"""

import httpx

from gridlens.auth.sessions import SessionHandle, SessionManager
from gridlens.contracts import ModelChoice
from gridlens.errors import AppError

MODELS_URL = "https://api.openai.com/v1/models"


class ModelCatalog:
    def __init__(self, sessions: SessionManager, *, transport: httpx.BaseTransport | None = None):
        self.sessions = sessions
        self.transport = transport

    def fetch(self, handle: SessionHandle) -> list[ModelChoice]:
        token = self.sessions.access_token(handle)
        try:
            with httpx.Client(timeout=20, transport=self.transport) as client:
                response = client.get(MODELS_URL, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            raise AppError(
                "MODEL_CATALOG_UNAVAILABLE", "The model list could not be loaded.", retryable=True
            ) from None
        if response.status_code == 401:
            raise AppError("AUTH_EXPIRED", "ChatGPT did not accept this session. Sign in again.")
        if response.status_code == 403:
            raise AppError(
                "PLAN_PERMISSION_MISSING", "This account cannot use ChatGPT plan models here."
            )
        if response.status_code == 429:
            raise AppError("USAGE_LIMITED", "The ChatGPT plan usage limit was reached.")
        if response.status_code != 200:
            raise AppError(
                "MODEL_CATALOG_UNAVAILABLE", "The model list could not be loaded.", retryable=True
            )
        if not self.sessions.is_current(handle):
            raise AppError("ACCOUNT_CHANGED", "The selected ChatGPT account changed.")
        return parse_models(response)


def parse_models(response: httpx.Response) -> list[ModelChoice]:
    try:
        models = response.json().get("models")
    except (ValueError, AttributeError):
        models = None
    if not isinstance(models, list):
        raise AppError("MODEL_CATALOG_UNAVAILABLE", "The model list was not understood.")
    choices, seen = [], set()
    for item in models:
        # Keep listed models in server order; skip malformed or hidden entries.
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug.strip() or slug in seen:
            continue
        name = item.get("display_name")
        display = name.strip() if isinstance(name, str) and name.strip() else slug
        choices.append(ModelChoice(slug=slug, display_name=display))
        seen.add(slug)
    return choices
