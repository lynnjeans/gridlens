from gridlens.contracts import DiscoveryRequest, SearchHitDTO
from gridlens.providers.fakes import FakeSearchProvider
from gridlens.repositories.sources import SourceRepository
from gridlens.services.discovery import DiscoveryService


def make_service(db, provider):
    return DiscoveryService(db, SourceRepository(db), provider, "fixture")


def test_operation_key_is_persistent_and_does_not_repeat_provider_calls(db):
    first_provider = FakeSearchProvider()
    first = make_service(db, first_provider).discover(
        DiscoveryRequest(topic="New Zealand grid connection"), "same-operation"
    )
    assert first_provider.calls == 1

    replacement_provider = FakeSearchProvider(fault="SHOULD_NOT_RUN")
    second = make_service(db, replacement_provider).discover(
        DiscoveryRequest(topic="a different topic"), "same-operation"
    )
    assert replacement_provider.calls == 0
    assert second == first

    with db.connect() as connection:
        run = connection.execute(
            "SELECT topic, status, calls_used, provider FROM search_runs"
        ).fetchone()
        assert tuple(run) == ("New Zealand grid connection", "completed", 1, "fixture")
        assert connection.execute("SELECT COUNT(*) FROM search_hits").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1


def test_manual_source_is_pending_lead_without_document_version(db):
    candidate = make_service(db, FakeSearchProvider()).add_source(
        "https://example.org/public-guide?utm_campaign=test&edition=2"
    )
    source = SourceRepository(db).get_source(candidate.source_id)
    assert source["canonical_url"] == "https://example.org/public-guide?edition=2"
    assert source["access_status"] == "unknown"
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 0


def test_more_than_ten_results_are_bounded(db):
    class ManyProvider:
        calls = 0

        def search(self, query, limit):
            self.calls += 1
            return [
                SearchHitDTO(
                    title=f"Source {index}",
                    url=f"https://example.org/{index}",
                    snippet="x",
                    provider_rank=index + 1,
                )
                for index in range(15)
            ]

    result = make_service(db, ManyProvider()).discover(
        DiscoveryRequest(topic="grid capacity", region="ALL"), "bounded"
    )
    assert len(result.candidates) == 10
