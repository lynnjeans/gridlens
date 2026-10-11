"""Tavily Search API adapter with no implicit retries or content fetching."""

from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from gridlens.contracts import SearchHitDTO
from gridlens.errors import AppError

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilySearchProvider:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ):
        if not api_key.get_secret_value():
            raise AppError("CONFIG_MISSING", "A Tavily search key is required in live mode.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._client_factory = client_factory

    def search(self, query: str, limit: int) -> list[SearchHitDTO]:
        query = query.strip()
        if not query or not 1 <= limit <= 10:
            raise AppError("INVALID_INPUT", "Search query and limit are invalid.")
        payload = {
            "query": query,
            "search_depth": "basic",
            "chunks_per_source": 1,
            "max_results": limit,
            "topic": "general",
            "include_published_date": True,
            "filter_by_published_date": False,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_image_descriptions": False,
            "include_favicon": False,
            "auto_parameters": False,
            "include_usage": False,
        }
        try:
            with self._client_factory(
                timeout=self._timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    TAVILY_SEARCH_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException:
            raise AppError("PROVIDER_TIMEOUT", "Search timed out.", retryable=True) from None
        except httpx.HTTPError:
            raise AppError(
                "PROVIDER_UNAVAILABLE", "Search service is unavailable.", retryable=True
            ) from None

        if response.status_code == 401:
            raise AppError("SEARCH_AUTH_FAILED", "Search authorization failed.")
        if response.status_code in {429, 432, 433}:
            raise AppError("RATE_LIMITED", "Search quota or rate limit was reached.")
        if response.status_code >= 500:
            raise AppError("PROVIDER_UNAVAILABLE", "Search service is unavailable.", retryable=True)
        if response.status_code >= 400:
            raise AppError("SEARCH_REQUEST_INVALID", "Search request was rejected.")
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            raise AppError("PROVIDER_RESPONSE_INVALID", "Search returned invalid data.") from None
        results = body.get("results")
        if not isinstance(results, list):
            raise AppError("PROVIDER_RESPONSE_INVALID", "Search results were missing.")

        hits: list[SearchHitDTO] = []
        for rank, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            published_at = item.get("published_date")
            if not isinstance(published_at, str) or not published_at.strip():
                published_at = None
            provider_id = item.get("id") if isinstance(item.get("id"), str) else None
            score = item.get("score") if isinstance(item.get("score"), int | float) else None
            try:
                hits.append(
                    SearchHitDTO(
                        title=item.get("title"),
                        url=item.get("url"),
                        snippet=item.get("content") if isinstance(item.get("content"), str) else "",
                        provider_rank=rank,
                        published_at=published_at,
                        metadata_evidence={
                            "provider": "tavily",
                            "provider_result_id": provider_id,
                            "provider_score": score,
                            "request_id": body.get("request_id")
                            if isinstance(body.get("request_id"), str)
                            else None,
                        },
                    )
                )
            except ValidationError:
                continue
        return hits[:limit]
