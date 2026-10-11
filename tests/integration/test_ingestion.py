import hashlib

import pytest

from gridlens.contracts import FetchedDocument, SearchHitDTO
from gridlens.documents.snapshots import SnapshotService
from gridlens.errors import AppError
from gridlens.providers.chroma_store import ChromaVectorStore
from gridlens.providers.fakes import FakeEmbeddingProvider, FakeTokenizer
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository
from gridlens.services.ingestion import IngestionService
from gridlens.services.review import ReviewService

pytest.importorskip("chromadb")

LONG = "".join(
    f"<p>Paragraph {i} explains a synthetic connection step with several words.</p>"
    for i in range(60)
)


class Fetcher:
    def __init__(self):
        self.body = f"<main><h1>Guide</h1>{LONG}</main>".encode()

    def fetch(self, url):
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            content_type="text/html",
            body=self.body,
            raw_sha256=hashlib.sha256(self.body).hexdigest(),
            fetched_at="2026-10-11T00:00:00+00:00",
            redirect_count=0,
        )


class World:
    def __init__(self, db, tmp_path):
        self.db = db
        self.root = tmp_path / "data/fixture"
        self.sources = SourceRepository(db)
        self.fetcher = Fetcher()
        self.snapshots = SnapshotService(
            db, self.sources, self.fetcher, self.root, max_pdf_pages=5, pdf_timeout_seconds=5
        )
        self.review = ReviewService(db, self.sources, self.root)
        self.research = ResearchRepository(db)
        self.source_id = self.sources.save_candidate(
            SearchHitDTO(
                title="Guide",
                url="https://synthetic.example/guide",
                snippet="s",
                provider_rank=1,
                jurisdiction="NZ",
            ),
            "https://synthetic.example/guide",
        )

    def approved_version(self, body_suffix=""):
        self.fetcher.body = f"<main><h1>Guide</h1>{LONG}{body_suffix}</main>".encode()
        preview = self.snapshots.capture(self.source_id)
        self.review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
        return preview.version_id

    def service(self, *, embeddings=None, vectors=None, before_publish=None):
        embeddings = embeddings or FakeEmbeddingProvider()
        service = IngestionService(
            self.db,
            self.review,
            embeddings=embeddings,
            tokenizer=FakeTokenizer(),
            vectors=vectors or self.store(),
            embedding_identity=embeddings.identity(),
            dimensions=16,
            chunk_tokens=30,
            chunk_overlap=5,
            max_input_tokens=512,
            before_publish=before_publish,
        )
        return service

    def store(self):
        from gridlens.documents.chunking import index_fingerprint

        fingerprint = index_fingerprint(FakeEmbeddingProvider().identity(), 30, 5)
        return ChromaVectorStore(self.root / "chroma", fingerprint, 16)

    def version(self, version_id):
        return self.sources.get_version(version_id)

    def eligible(self, service):
        return [v["id"] for v in self.research.eligible_versions(service.fingerprint)]

    def count(self, sql, *args):
        with self.db.connect() as c:
            return c.execute(sql, args).fetchone()[0]


@pytest.fixture
def world(db, tmp_path):
    return World(db, tmp_path)


class FailingStore:
    """Wraps a real store and fails the Nth upsert."""

    def __init__(self, inner, fail_on=2):
        self.inner = inner
        self.fail_on = fail_on
        self.upserts = 0

    def upsert(self, chunks, vectors):
        self.upserts += 1
        if self.upserts == self.fail_on:
            raise AppError("VECTOR_STORE_FAILED", "Synthetic index failure.")
        self.inner.upsert(chunks, vectors)

    def stored_ids(self, version_id):
        return self.inner.stored_ids(version_id)

    def query(self, *args):
        return self.inner.query(*args)

    def delete_version(self, version_id):
        self.inner.delete_version(version_id)


class SwappedIdsStore(FailingStore):
    """Reports the right number of IDs, but not the right IDs."""

    def __init__(self, inner):
        super().__init__(inner, fail_on=0)

    def stored_ids(self, version_id):
        ids = sorted(self.inner.stored_ids(version_id))
        return set(ids[:-1]) | {"0" * 64}


def test_successful_ingestion_publishes_ready_active(world):
    version_id = world.approved_version()
    service = world.service()
    result = service.ingest(version_id, "op-1")
    assert result.status == "completed" and result.expected_chunks > 16
    assert result.indexed_chunks == result.expected_chunks
    row = world.version(version_id)
    assert (row["ingestion_status"], row["version_status"]) == ("ready", "active")
    assert row["index_fingerprint"] == service.fingerprint
    assert world.eligible(service) == [version_id]
    with world.db.connect() as c:
        chunk_ids = {r[0] for r in c.execute("SELECT id FROM chunks")}
    assert world.store().stored_ids(version_id) == chunk_ids
    assert world.count("SELECT COUNT(*) FROM ingestion_runs WHERE status='completed'") == 1
    assert world.count("SELECT stage FROM ingestion_runs") == "published"


def test_replay_and_ready_are_noops_without_duplicates(world):
    version_id = world.approved_version()
    service = world.service()
    first = service.ingest(version_id, "op-1")
    chunks = world.count("SELECT COUNT(*) FROM chunks")
    assert service.ingest(version_id, "op-1") == first
    again = service.ingest(version_id, "op-2")
    assert again.status == "noop" and again.ingestion_status == "ready"
    assert world.count("SELECT COUNT(*) FROM ingestion_runs") == 1
    assert world.count("SELECT COUNT(*) FROM chunks") == chunks
    assert len(world.store().stored_ids(version_id)) == chunks


def test_embedding_failure_is_not_retrievable_and_retry_does_not_duplicate(world):
    version_id = world.approved_version()
    failed = world.service(embeddings=FakeEmbeddingProvider("LOCAL_MODEL_MISSING")).ingest(
        version_id, "op-1"
    )
    assert failed.status == "failed" and failed.error_code == "LOCAL_MODEL_MISSING"
    row = world.version(version_id)
    assert (row["ingestion_status"], row["version_status"]) == ("failed", "candidate")
    assert row["review_status"] == "approved"
    service = world.service()
    assert world.eligible(service) == []
    chunks = world.count("SELECT COUNT(*) FROM chunks")

    retried = service.ingest(version_id, "op-2")
    assert retried.status == "completed"
    assert world.count("SELECT COUNT(*) FROM chunks") == chunks
    assert world.count("SELECT MAX(attempt) FROM ingestion_runs") == 2
    assert world.eligible(service) == [version_id]


def test_partial_index_failure_keeps_version_ineligible(world):
    version_id = world.approved_version()
    store = FailingStore(world.store(), fail_on=2)
    result = world.service(vectors=store).ingest(version_id, "op-1")
    assert result.status == "failed" and result.error_code == "VECTOR_STORE_FAILED"
    assert 0 < result.indexed_chunks < result.expected_chunks
    assert world.store().stored_ids(version_id)  # partial vectors exist...
    assert world.eligible(world.service()) == []  # ...but grant no eligibility


def test_same_count_with_different_ids_fails_verification(world):
    version_id = world.approved_version()
    result = world.service(vectors=SwappedIdsStore(world.store())).ingest(version_id, "op-1")
    assert result.status == "failed" and result.error_code == "INDEX_INCOMPLETE"
    assert world.version(version_id)["version_status"] == "candidate"


def test_revocation_during_indexing_blocks_publication(world):
    version_id = world.approved_version()

    def revoke(vid):
        world.review.revoke(vid, "Researcher", "Withdrawn during indexing")

    service = world.service(before_publish=revoke)
    result = service.ingest(version_id, "op-1")
    assert result.status == "failed" and result.error_code == "REVIEW_CHANGED"
    row = world.version(version_id)
    assert (row["review_status"], row["version_status"]) == ("revoked", "candidate")
    assert world.eligible(service) == []


def test_second_tab_cannot_start_a_parallel_run(world):
    version_id = world.approved_version()
    attempts = []

    def second_tab(vid):
        with pytest.raises(AppError) as raised:
            world.service().ingest(vid, "op-2")
        attempts.append(raised.value.code)

    result = world.service(before_publish=second_tab).ingest(version_id, "op-1")
    assert attempts == ["INGESTION_IN_PROGRESS"]
    assert result.status == "completed"
    assert world.count("SELECT COUNT(*) FROM ingestion_runs") == 1


def test_failed_new_version_keeps_old_active_and_success_supersedes_it(world):
    service = world.service()
    old = world.approved_version()
    service.ingest(old, "op-old")
    new = world.approved_version("<p>Revised synthetic edition.</p>")
    assert new != old

    failed = world.service(embeddings=FakeEmbeddingProvider("LOCAL_MODEL_MISSING")).ingest(
        new, "op-new-1"
    )
    assert failed.status == "failed"
    assert world.version(old)["version_status"] == "active"
    assert world.eligible(service) == [old]

    assert service.ingest(new, "op-new-2").status == "completed"
    assert world.version(old)["version_status"] == "superseded"
    assert world.version(new)["version_status"] == "active"
    assert world.eligible(service) == [new]


def test_publish_transaction_failure_rolls_back_everything(world):
    service = world.service()
    old = world.approved_version()
    service.ingest(old, "op-old")
    new = world.approved_version("<p>Revised synthetic edition.</p>")
    with world.db.transaction() as c:
        c.execute(
            "CREATE TRIGGER fail_publish BEFORE UPDATE ON ingestion_runs "
            "WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
        )
    with pytest.raises(AppError) as raised:
        service.ingest(new, "op-new")
    assert raised.value.code == "INGESTION_FAILED"
    assert world.version(old)["version_status"] == "active"
    new_row = world.version(new)
    assert (new_row["ingestion_status"], new_row["version_status"]) == ("failed", "candidate")
    assert world.eligible(service) == [old]


def test_unapproved_or_mismatched_versions_are_refused(world):
    preview = world.snapshots.capture(world.source_id)
    service = world.service()
    with pytest.raises(AppError) as raised:
        service.ingest(preview.version_id, "op-1")
    assert raised.value.code == "REVIEW_REQUIRED"
    assert world.count("SELECT COUNT(*) FROM ingestion_runs") == 0

    world.review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    service.ingest(preview.version_id, "op-2")
    other = world.service()
    other.fingerprint = "e" * 64
    with pytest.raises(AppError) as raised:
        other.ingest(preview.version_id, "op-3")
    assert raised.value.code == "INDEX_CONFIG_MISMATCH"
