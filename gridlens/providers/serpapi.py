"""SerpApi Google Search adapter with no implicit retries or content fetching."""

from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from gridlens.contracts import SearchHitDTO
from gridlens.errors import AppError

SERPAPI_SEARCH_URL = "https://serpapi.com/search"
# SerpApi reports an engine that returned nothing as a successful search.
_NO_RESULTS = "hasn't returned any results"


class SerpApiSearchProvider:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ):
        if not api_key.get_secret_value():
            raise AppError("CONFIG_MISSING", "A SerpApi search key is required in live mode.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._client_factory = client_factory

    def search(self, query: str, limit: int) -> list[SearchHitDTO]:
        query = query.strip()
        if not query or not 1 <= limit <= 10:
            raise AppError("INVALID_INPUT", "Search query and limit are invalid.")
        # The documented API authenticates only by query parameter; the key never
        # reaches logs because httpx loggers are redacted (gridlens.oplog).
        params = {
            "engine": "google",
            "q": query,
            "hl": "en",
            "safe": "active",
            "output": "json",
            "api_key": self._api_key.get_secret_value(),
        }
        try:
            with self._client_factory(
                timeout=self._timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(SERPAPI_SEARCH_URL, params=params)
        except httpx.TimeoutException:
            raise AppError("PROVIDER_TIMEOUT", "Search timed out.", retryable=True) from None
        except httpx.HTTPError:
            raise AppError(
                "PROVIDER_UNAVAILABLE", "Search service is unavailable.", retryable=True
            ) from None

        if response.status_code in {401, 403}:
            raise AppError("SEARCH_AUTH_FAILED", "Search authorization failed.")
        if response.status_code == 429:
            raise AppError("RATE_LIMITED", "Search quota or rate limit was reached.")
        if response.status_code >= 500:
            raise AppError("PROVIDER_UNAVAILABLE", "Search service is unavailable.", retryable=True)
        if response.status_code >= 400:
            raise AppError("SEARCH_REQUEST_INVALID", "Search request was rejected.")
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            raise AppError("PROVIDER_RESPONSE_INVALID", "Search returned invalid data.") from None
        if not isinstance(body, dict):
            raise AppError("PROVIDER_RESPONSE_INVALID", "Search returned invalid data.")
        results = body.get("organic_results")
        error = body.get("error")
        if results is None and isinstance(error, str) and _NO_RESULTS in error:
            return []
        if error is not None or not isinstance(results, list):
            raise AppError("PROVIDER_RESPONSE_INVALID", "Search results were missing.")

        metadata = body.get("search_metadata")
        search_id = metadata.get("id") if isinstance(metadata, dict) else None
        hits: list[SearchHitDTO] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            published_at = item.get("date")
            if not isinstance(published_at, str) or not published_at.strip():
                published_at = None
            source = item.get("source") if isinstance(item.get("source"), str) else None
            try:
                hits.append(
                    SearchHitDTO(
                        title=item.get("title"),
                        url=item.get("link"),
                        snippet=item.get("snippet") if isinstance(item.get("snippet"), str) else "",
                        provider_rank=len(hits) + 1,
                        published_at=published_at,
                        metadata_evidence={
                            "provider": "serpapi",
                            "provider_position": item.get("position")
                            if isinstance(item.get("position"), int)
                            else None,
                            "provider_source_label": source,
                            "request_id": search_id if isinstance(search_id, str) else None,
                        },
                    )
                )
            except ValidationError:
                continue
        return hits[:limit]
