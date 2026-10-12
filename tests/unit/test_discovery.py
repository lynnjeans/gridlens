import pytest

from gridlens.contracts import DiscoveryRequest, SearchHitDTO
from gridlens.errors import AppError
from gridlens.repositories.sources import SourceRepository
from gridlens.services.discovery import DiscoveryService, canonicalize_public_url, queries_for


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def search(self, query, limit):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, AppError):
            raise response
        return response[:limit]


def hit(url, rank=1, score=0.5, date=None):
    return SearchHitDTO(
        title=f"Source {rank}",
        url=url,
        snippet="Search result snippet",
        provider_rank=rank,
        published_at=date,
        metadata_evidence={"provider_score": score},
    )


def service(db, provider):
    return DiscoveryService(db, SourceRepository(db), provider, "fixture")


def test_canonical_url_removes_tracking_but_preserves_functional_parameters():
    assert (
        canonicalize_public_url("HTTPS://Example.org//guide/?b=2&utm_source=x&a=1&ref=mail#section")
        == "https://example.org/guide?a=1&b=2"
    )
    assert canonicalize_public_url("http://EXAMPLE.org:80/") == "http://example.org/"


@pytest.mark.parametrize(
    "url", ["ftp://example.org/x", "http://localhost/x", "http://10.0.0.2/x", "http://[::1]/"]
)
def test_canonical_url_rejects_non_public_urls(url):
    with pytest.raises(AppError):
        canonicalize_public_url(url)


def test_query_generation_is_bounded_and_meaning_preserving():
    request = DiscoveryRequest(
        topic="large-load grid connections",
        region="NZ",
        source_types=["policy", "technical"],
    )
    assert queries_for(request) == [
        "large-load grid connections",
        "large-load grid connections New Zealand",
        "large-load grid connections policy technical",
    ]


def test_discovery_deduplicates_stably_and_preserves_partial_results(db):
    provider = ScriptedProvider(
        [
            [hit("https://example.org/guide?utm_source=a", rank=2, score=0.4)],
            AppError("RATE_LIMITED", "Synthetic limit"),
            [
                hit("https://example.org/guide", rank=1, score=0.9),
                hit("https://example.org/report?year=2025", rank=2, date=None),
            ],
        ]
    )
    result = service(db, provider).discover(
        DiscoveryRequest(
            topic="grid connection queue",
            region="NZ",
            source_types=["policy"],
        ),
        "partial-operation",
    )
    assert provider.calls == 3
    assert result.status == "partial"
    assert result.error_codes == ["RATE_LIMITED"]
    assert [candidate.url for candidate in result.candidates] == [
        "https://example.org/guide",
        "https://example.org/report?year=2025",
    ]
    assert result.candidates[1].published_at is None


def test_all_errors_create_failed_run(db):
    provider = ScriptedProvider([AppError("PROVIDER_TIMEOUT", "timeout")] * 2)
    result = service(db, provider).discover(
        DiscoveryRequest(topic="grid capacity", region="NZ"), "failed-operation"
    )
    assert result.status == "failed"
    assert result.candidates == []
    assert result.error_codes == ["PROVIDER_TIMEOUT", "PROVIDER_TIMEOUT"]


def test_live_run_records_the_selected_provider(db):
    provider = ScriptedProvider([[hit("https://example.org/guide")]] * 3)
    DiscoveryService(db, SourceRepository(db), provider, "live", provider_name="serpapi").discover(
        DiscoveryRequest(topic="grid capacity", region="NZ"), "serpapi-operation"
    )
    with db.transaction() as c:
        assert c.execute("SELECT provider FROM search_runs").fetchone()[0] == "serpapi"


def test_bootstrap_builds_only_the_selected_live_provider(tmp_path):
    from pydantic import SecretStr

    from gridlens.bootstrap import build_container
    from gridlens.config import Settings
    from gridlens.providers.serpapi import SerpApiSearchProvider

    settings = Settings(
        project_root=tmp_path,
        mode="live",
        auth_dir=tmp_path.parent / f"{tmp_path.name}-auth",
        search_provider="serpapi",
        serpapi_api_key=SecretStr("serp-secret"),
    )
    discovery = build_container(settings).discovery
    assert isinstance(discovery.provider, SerpApiSearchProvider)
    assert discovery.provider_name == "serpapi"
