import httpx
import pytest
from pydantic import SecretStr

from gridlens.errors import AppError
from gridlens.providers.tavily import TAVILY_SEARCH_URL, TavilySearchProvider


def provider(handler):
    return TavilySearchProvider(
        SecretStr("private-test-key"), transport=httpx.MockTransport(handler)
    )


def test_maps_search_contract_without_requesting_generated_content():
    observed = {}

    def handler(request):
        observed["authorization"] = request.headers["Authorization"]
        observed["payload"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "answer": "must be ignored",
                "results": [
                    {
                        "id": "r1",
                        "title": "Grid connection guide",
                        "url": "https://example.org/guide",
                        "content": "Public search snippet.",
                        "score": 0.91,
                        "published_date": "2025-06-01",
                    }
                ],
            },
        )

    hits = provider(handler).search("grid connection", 5)
    assert observed["authorization"] == "Bearer private-test-key"
    assert observed["payload"] == {
        "query": "grid connection",
        "search_depth": "basic",
        "chunks_per_source": 1,
        "max_results": 5,
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
    assert len(hits) == 1
    assert hits[0].title == "Grid connection guide"
    assert hits[0].snippet == "Public search snippet."
    assert hits[0].published_at == "2025-06-01"
    assert hits[0].publisher is None
    assert hits[0].metadata_evidence["provider_score"] == 0.91


def test_empty_results_are_success_and_malformed_records_are_skipped():
    empty = provider(lambda request: httpx.Response(200, json={"results": []}))
    assert empty.search("topic", 10) == []

    malformed = provider(
        lambda request: httpx.Response(
            200,
            json={
                "results": [
                    None,
                    {"title": "missing URL", "content": "x"},
                    {
                        "title": "Valid",
                        "url": "https://example.org",
                        "content": "x",
                        "published_date": 123,
                    },
                ]
            },
        )
    )
    hits = malformed.search("topic", 10)
    assert [hit.title for hit in hits] == ["Valid"]
    assert hits[0].published_at is None


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "SEARCH_AUTH_FAILED", False),
        (429, "RATE_LIMITED", False),
        (432, "RATE_LIMITED", False),
        (500, "PROVIDER_UNAVAILABLE", True),
        (400, "SEARCH_REQUEST_INVALID", False),
    ],
)
def test_maps_http_errors_without_retry(status, code, retryable):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    with pytest.raises(AppError) as raised:
        provider(handler).search("topic", 10)
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert calls == 1


def test_maps_timeout_and_invalid_response():
    def timeout(request):
        raise httpx.ReadTimeout("secret upstream detail", request=request)

    with pytest.raises(AppError, match="Search timed out") as raised:
        provider(timeout).search("topic", 10)
    assert raised.value.code == "PROVIDER_TIMEOUT"
    assert "secret" not in str(raised.value)

    invalid = provider(lambda request: httpx.Response(200, content=b"not-json"))
    with pytest.raises(AppError) as raised:
        invalid.search("topic", 10)
    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"


def test_uses_only_the_documented_endpoint():
    def handler(request):
        assert str(request.url) == TAVILY_SEARCH_URL
        return httpx.Response(200, json={"results": []})

    provider(handler).search("topic", 1)
