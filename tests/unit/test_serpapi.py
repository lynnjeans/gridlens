import httpx
import pytest
from pydantic import SecretStr

from gridlens.errors import AppError
from gridlens.providers.serpapi import SERPAPI_SEARCH_URL, SerpApiSearchProvider


def provider(handler):
    return SerpApiSearchProvider(
        SecretStr("private-test-key"), transport=httpx.MockTransport(handler)
    )


def test_maps_search_contract_without_requesting_generated_content():
    observed = {}

    def handler(request):
        observed["method"] = request.method
        observed["params"] = dict(request.url.params)
        observed["has_authorization"] = "Authorization" in request.headers
        return httpx.Response(
            200,
            json={
                "search_metadata": {"id": "search-1", "status": "Success"},
                "answer_box": {"answer": "must be ignored"},
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Grid connection guide",
                        "link": "https://example.org/guide",
                        "snippet": "Public search snippet.",
                        "source": "Example Org",
                        "date": "Jun 1, 2025",
                    },
                    {"position": 2, "title": "No snippet", "link": "https://example.org/b"},
                ],
            },
        )

    hits = provider(handler).search("grid connection", 5)
    assert observed["method"] == "GET"
    assert observed["params"] == {
        "engine": "google",
        "q": "grid connection",
        "hl": "en",
        "safe": "active",
        "output": "json",
        "api_key": "private-test-key",
    }
    assert observed["has_authorization"] is False
    assert [hit.provider_rank for hit in hits] == [1, 2]
    assert hits[0].title == "Grid connection guide"
    assert hits[0].url == "https://example.org/guide"
    assert hits[0].snippet == "Public search snippet."
    assert hits[0].published_at == "Jun 1, 2025"
    # The site label is evidence only; publisher stays unverified.
    assert hits[0].publisher is None
    assert hits[0].metadata_evidence == {
        "provider": "serpapi",
        "provider_position": 1,
        "provider_source_label": "Example Org",
        "request_id": "search-1",
    }
    assert hits[1].snippet == "" and hits[1].published_at is None


def test_no_results_is_success_and_malformed_records_are_skipped():
    empty = provider(
        lambda request: httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "error": "Google hasn't returned any results for this query.",
            },
        )
    )
    assert empty.search("topic", 10) == []
    assert (
        provider(lambda r: httpx.Response(200, json={"organic_results": []})).search("topic", 10)
        == []
    )

    malformed = provider(
        lambda request: httpx.Response(
            200,
            json={
                "organic_results": [
                    None,
                    {"title": "missing link", "snippet": "x"},
                    {"title": "Valid", "link": "https://example.org", "date": 123},
                ]
            },
        )
    )
    hits = malformed.search("topic", 10)
    assert [hit.title for hit in hits] == ["Valid"]
    assert hits[0].provider_rank == 1
    assert hits[0].published_at is None


def test_limit_truncates_results():
    results = [
        {"title": f"R{i}", "link": f"https://example.org/{i}", "snippet": ""} for i in range(10)
    ]
    hits = provider(lambda r: httpx.Response(200, json={"organic_results": results})).search(
        "topic", 3
    )
    assert [hit.title for hit in hits] == ["R0", "R1", "R2"]


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "SEARCH_AUTH_FAILED", False),
        (403, "SEARCH_AUTH_FAILED", False),
        (429, "RATE_LIMITED", False),
        (500, "PROVIDER_UNAVAILABLE", True),
        (503, "PROVIDER_UNAVAILABLE", True),
        (400, "SEARCH_REQUEST_INVALID", False),
    ],
)
def test_maps_http_errors_without_retry(status, code, retryable):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "upstream private-test-key detail"})

    with pytest.raises(AppError) as raised:
        provider(handler).search("topic", 10)
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert "private-test-key" not in str(raised.value)
    assert calls == 1


def test_maps_timeout_unexpected_error_and_invalid_response():
    def timeout(request):
        raise httpx.ReadTimeout(f"timeout for {request.url}", request=request)

    with pytest.raises(AppError, match="Search timed out") as raised:
        provider(timeout).search("topic", 10)
    assert raised.value.code == "PROVIDER_TIMEOUT"
    assert "private-test-key" not in str(raised.value)

    for response in (
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"error": "Invalid API key."}),
        httpx.Response(200, json={"search_metadata": {"status": "Success"}}),
    ):
        with pytest.raises(AppError) as raised:
            provider(lambda request, response=response: response).search("topic", 10)
        assert raised.value.code == "PROVIDER_RESPONSE_INVALID"


def test_rejects_invalid_input_and_missing_key_without_calling():
    def handler(request):
        raise AssertionError("must not call")

    for query, limit in (("  ", 5), ("topic", 0), ("topic", 11)):
        with pytest.raises(AppError) as raised:
            provider(handler).search(query, limit)
        assert raised.value.code == "INVALID_INPUT"
    with pytest.raises(AppError) as raised:
        SerpApiSearchProvider(SecretStr(""))
    assert raised.value.code == "CONFIG_MISSING"


def test_uses_only_the_documented_endpoint():
    def handler(request):
        assert str(request.url).split("?")[0] == SERPAPI_SEARCH_URL
        return httpx.Response(200, json={"organic_results": []})

    provider(handler).search("topic", 1)
