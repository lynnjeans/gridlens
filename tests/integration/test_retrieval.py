import hashlib

import pytest

from gridlens.contracts import FetchedDocument, RetrievalFilters, SearchHitDTO, VectorHit
from gridlens.documents.chunking import index_fingerprint
from gridlens.documents.snapshots import SnapshotService
from gridlens.errors import AppError
from gridlens.providers.chroma_store import ChromaVectorStore
from gridlens.providers.fakes import FakeEmbeddingProvider, FakeTokenizer
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository
from gridlens.services.ingestion import IngestionService
from gridlens.services.retrieval import RetrievalService
from gridlens.services.review import ReviewService

pytest.importorskip("chromadb")

FINGERPRINT = index_fingerprint(FakeEmbeddingProvider().identity(), 30, 5)


class Fetcher:
    def __init__(self):
        self.bodies = {}

    def fetch(self, url):
        body = self.bodies[url]
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            content_type="text/html",
            body=body,
            raw_sha256=hashlib.sha256(body).hexdigest(),
            fetched_at="2026-10-12T00:00:00+00:00",
            redirect_count=0,
        )


class Spy:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def __getattr__(self, name):
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        def wrapped(*args, **kwargs):
            self.calls += 1
            return attribute(*args, **kwargs)

        return wrapped


class Corpus:
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
        self.store = ChromaVectorStore(self.root / "chroma", FINGERPRINT, 16)
        self.ingestion = IngestionService(
            db,
            self.review,
            embeddings=FakeEmbeddingProvider(),
            tokenizer=FakeTokenizer(),
            vectors=self.store,
            embedding_identity=FakeEmbeddingProvider().identity(),
            dimensions=16,
            chunk_tokens=30,
            chunk_overlap=5,
            max_input_tokens=512,
        )
        self.keys = 0

    def source(self, name, jurisdiction="NZ", source_type="policy"):
        url = f"https://synthetic.example/{name}"
        return self.sources.save_candidate(
            SearchHitDTO(
                title=name,
                url=url,
                snippet="s",
                provider_rank=1,
                jurisdiction=jurisdiction,
                source_type=source_type,
            ),
            url,
        ), url

    def version(self, name, text, *, approve=True, ingest=True, **labels):
        source_id, url = self.source(name, **labels)
        return self.revise(source_id, url, text, approve=approve, ingest=ingest)

    def revise(self, source_id, url, text, *, approve=True, ingest=True):
        self.fetcher.bodies[url] = f"<main><h1>{url}</h1><p>{text}</p></main>".encode()
        preview = self.snapshots.capture(source_id)
        if approve:
            self.review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
        if ingest:
            self.keys += 1
            assert self.ingestion.ingest(preview.version_id, f"k{self.keys}").status == "completed"
        return preview.version_id

    def service(self, *, embeddings=None, vectors=None, context_k=5, max_tokens=4000):
        return RetrievalService(
            self.research,
            embeddings=embeddings or FakeEmbeddingProvider(),
            vectors=vectors or self.store,
            index_fingerprint=FINGERPRINT,
            top_k=10,
            context_k=context_k,
            max_context_tokens=max_tokens,
        )


@pytest.fixture
def corpus(db, tmp_path):
    return Corpus(db, tmp_path)


TEXT = "grid connection application process for a data centre load"


def versions_in(context):
    return {chunk.version_id for chunk in context.chunks}


@pytest.fixture
def mixed(corpus):
    v = {}
    v["nz"] = corpus.version("nz", TEXT + " nz")
    v["global"] = corpus.version(
        "global", TEXT + " global", jurisdiction="GLOBAL", source_type="technical"
    )
    v["us"] = corpus.version("us", TEXT + " us", jurisdiction="US", source_type="paper")
    v["unknown"] = corpus.version("unknown", TEXT + " unknown", jurisdiction="UNKNOWN")
    v["pending"] = corpus.version("pending", TEXT + " pending", approve=False, ingest=False)
    rejected = corpus.version("rejected", TEXT + " rejected", approve=False, ingest=False)
    corpus.review.reject(rejected, "Researcher", "Not relevant")
    v["rejected"] = rejected
    failed = corpus.version("failed", TEXT + " failed", ingest=False)
    broken = IngestionService(
        corpus.db,
        corpus.review,
        embeddings=FakeEmbeddingProvider("LOCAL_MODEL_MISSING"),
        tokenizer=FakeTokenizer(),
        vectors=corpus.store,
        embedding_identity=FakeEmbeddingProvider().identity(),
        dimensions=16,
        chunk_tokens=30,
        chunk_overlap=5,
        max_input_tokens=512,
    )
    assert broken.ingest(failed, "broken").status == "failed"
    v["failed"] = failed
    revoked = corpus.version("revoked", TEXT + " revoked")
    corpus.review.revoke(revoked, "Researcher", "Withdrawn")
    v["revoked"] = revoked
    source_id, url = corpus.source("edition")
    v["superseded"] = corpus.revise(source_id, url, TEXT + " old edition")
    v["current"] = corpus.revise(source_id, url, TEXT + " new edition")
    return v


def test_ineligible_states_never_enter_context_even_with_stale_vectors(corpus, mixed):
    # Revoked and superseded versions still have vectors in Chroma.
    assert corpus.store.stored_ids(mixed["revoked"])
    assert corpus.store.stored_ids(mixed["superseded"])
    context = corpus.service().retrieve(
        "grid connection application", RetrievalFilters(region="ALL")
    )
    found = versions_in(context)
    assert found <= {mixed[k] for k in ("nz", "global", "us", "unknown", "current")}
    for state in ("pending", "rejected", "failed", "revoked", "superseded"):
        assert mixed[state] not in found
        assert mixed[state] not in context.eligible_version_ids
    assert set(context.eligible_version_ids) == {
        mixed[k] for k in ("nz", "global", "us", "unknown", "current")
    }


def test_region_rules_include_global_and_exclude_unknown_by_default(corpus, mixed):
    service = corpus.service()
    nz = service.retrieve("grid connection application", RetrievalFilters())
    assert set(nz.eligible_version_ids) == {mixed["nz"], mixed["global"], mixed["current"]}
    assert nz.diagnostics["excluded_by_region"] == {"UNKNOWN": 1, "US": 1}
    us = service.retrieve("grid connection application", RetrievalFilters(region="US"))
    assert set(us.eligible_version_ids) == {mixed["us"], mixed["global"]}
    only_global = service.retrieve("grid connection", RetrievalFilters(region="GLOBAL"))
    assert set(only_global.eligible_version_ids) == {mixed["global"]}
    typed = service.retrieve(
        "grid connection", RetrievalFilters(region="ALL", source_types=["paper", "technical"])
    )
    assert set(typed.eligible_version_ids) == {mixed["us"], mixed["global"]}
    assert typed.diagnostics["excluded_by_type"] == {"policy": 3}


def test_empty_library_and_excluded_filters_call_no_models(corpus):
    embeddings, vectors = Spy(FakeEmbeddingProvider()), Spy(corpus.store)
    service = corpus.service(embeddings=embeddings, vectors=vectors)
    empty = service.retrieve("grid connection", RetrievalFilters())
    assert empty.chunks == [] and empty.diagnostics["reason"] == "no_approved_sources"
    corpus.version("us-only", TEXT, jurisdiction="US")
    mismatch = service.retrieve("grid connection", RetrievalFilters(region="NZ"))
    assert mismatch.chunks == [] and mismatch.diagnostics["reason"] == "filters_excluded_all"
    assert mismatch.diagnostics["excluded_by_region"] == {"US": 1}
    assert embeddings.calls == 0 and vectors.calls == 0


class ForeignIds:
    """A misbehaving store that also returns IDs outside the whitelist."""

    def __init__(self, inner, extra):
        self.inner = inner
        self.extra = extra

    def query(self, vector, eligible, k):
        hits = self.inner.query(vector, eligible, k)
        return [VectorHit(chunk_id=i, distance=0.0) for i in self.extra] + hits


def test_out_of_scope_ids_from_the_store_are_dropped(corpus, mixed):
    revoked_ids = sorted(corpus.store.stored_ids(mixed["revoked"]))
    store = ForeignIds(corpus.store, ["unknown-id", *revoked_ids])
    context = corpus.service(vectors=store).retrieve("grid connection", RetrievalFilters())
    assert context.diagnostics["dropped_out_of_scope"] == 1 + len(revoked_ids)
    assert mixed["revoked"] not in versions_in(context)
    assert context.chunks


class RevokeDuringQuery:
    def __init__(self, corpus, version_id):
        self.corpus = corpus
        self.version_id = version_id

    def query(self, vector, eligible, k):
        hits = self.corpus.store.query(vector, eligible, k)
        self.corpus.review.revoke(self.version_id, "Researcher", "Changed mid-query")
        return hits


def test_status_change_during_retrieval_is_rechecked(corpus):
    only = corpus.version("only", TEXT)
    store = RevokeDuringQuery(corpus, only)
    context = corpus.service(vectors=store).retrieve("grid connection", RetrievalFilters())
    assert context.chunks == []
    assert context.diagnostics["reason"] == "stale_context"
    assert context.diagnostics["dropped_after_recheck"] > 0
    assert only not in context.eligible_version_ids


class ReadingOrder:
    """Ranks every eligible chunk by its position, so neighbours rank next to each other."""

    def __init__(self, corpus):
        self.corpus = corpus

    def query(self, vector, eligible, k):
        with self.corpus.db.connect() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM chunks ORDER BY ordinal")]
        return [VectorHit(chunk_id=i, distance=n / 100) for n, i in enumerate(ids[:k])]


def test_context_limits_and_overlap_dedup(corpus):
    long_text = " ".join(f"grid connection step {i} requires review" for i in range(60))
    version_id = corpus.version("long", long_text)
    service = corpus.service(vectors=ReadingOrder(corpus))
    context = service.retrieve("grid connection step review", RetrievalFilters())
    # Adjacent windows of one paragraph overlap; the higher-ranked one wins each time.
    assert [c.ordinal for c in context.chunks] == [0, 2, 4, 6, 8]
    assert context.diagnostics["skipped_overlapping"] == 4
    assert context.diagnostics["context_tokens"] <= 4000
    assert all(c.version_id == version_id and c.source_segment_ids for c in context.chunks)

    tight = corpus.service(max_tokens=40).retrieve("grid connection", RetrievalFilters())
    assert sum(c.token_count for c in tight.chunks) <= 40
    assert tight.diagnostics["skipped_over_budget"] > 0


def test_chunks_carry_authoritative_text_and_locator(corpus):
    version_id = corpus.version("guide", TEXT)
    [chunk] = corpus.service().retrieve("data centre load", RetrievalFilters()).chunks
    with corpus.db.connect() as c:
        row = c.execute(
            "SELECT text, locator_json FROM chunks WHERE id=?", (chunk.chunk_id,)
        ).fetchone()
    assert chunk.text == row["text"] and chunk.version_id == version_id
    assert chunk.locator.paragraph_index == 1
    assert chunk.index_fingerprint == FINGERPRINT


def test_rows_without_provenance_are_dropped(corpus):
    corpus.version("legacy", TEXT)
    with corpus.db.transaction() as c:
        c.execute("UPDATE chunks SET source_segment_ids_json='[]'")
    context = corpus.service().retrieve("grid connection", RetrievalFilters())
    assert context.chunks == [] and context.diagnostics["dropped_without_provenance"] == 1


def test_question_length_is_validated(corpus):
    with pytest.raises(AppError) as raised:
        corpus.service().retrieve("  a ", RetrievalFilters())
    assert raised.value.code == "INVALID_INPUT"
