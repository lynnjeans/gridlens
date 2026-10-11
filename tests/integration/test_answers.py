import hashlib
import json
from types import SimpleNamespace

import pytest

from gridlens.contracts import AnswerDraft, FetchedDocument, RetrievalFilters, SearchHitDTO
from gridlens.documents.chunking import index_fingerprint
from gridlens.documents.snapshots import SnapshotService
from gridlens.errors import AppError
from gridlens.providers.chroma_store import ChromaVectorStore
from gridlens.providers.fakes import FakeAnswerProvider, FakeEmbeddingProvider, FakeTokenizer
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository
from gridlens.services.answers import AnswerService
from gridlens.services.ingestion import IngestionService
from gridlens.services.retrieval import RetrievalService
from gridlens.services.review import ReviewService

pytest.importorskip("chromadb")

FINGERPRINT = index_fingerprint(FakeEmbeddingProvider().identity(), 30, 5)
TEXT = "The synthetic process starts with an application to the operator."


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


class World:
    def __init__(self, db, tmp_path):
        self.db = db
        root = tmp_path / "data/fixture"
        self.sources = SourceRepository(db)
        self.fetcher = Fetcher()
        self.snapshots = SnapshotService(
            db, self.sources, self.fetcher, root, max_pdf_pages=5, pdf_timeout_seconds=5
        )
        self.review = ReviewService(db, self.sources, root)
        self.research = ResearchRepository(db)
        store = ChromaVectorStore(root / "chroma", FINGERPRINT, 16)
        embeddings = FakeEmbeddingProvider()
        self.ingestion = IngestionService(
            db,
            self.review,
            embeddings=embeddings,
            tokenizer=FakeTokenizer(),
            vectors=store,
            embedding_identity=embeddings.identity(),
            dimensions=16,
            chunk_tokens=30,
            chunk_overlap=5,
            max_input_tokens=512,
        )
        self.retrieval = RetrievalService(
            self.research,
            embeddings=embeddings,
            vectors=store,
            index_fingerprint=FINGERPRINT,
            top_k=10,
            context_k=5,
            max_context_tokens=4000,
        )
        self.service = AnswerService(db, self.research, self.retrieval, mode="fixture")
        self.n = 0

    def publish(self, name="guide", text=TEXT, jurisdiction="NZ"):
        url = f"https://synthetic.example/{name}"
        source_id = self.sources.save_candidate(
            SearchHitDTO(
                title=f"{name} title",
                url=url,
                snippet="s",
                provider_rank=1,
                jurisdiction=jurisdiction,
                source_type="policy",
            ),
            url,
        )
        return self.revise(source_id, url, text)

    def revise(self, source_id, url, text):
        self.fetcher.bodies[url] = f"<main><h1>Guide</h1><p>{text}</p></main>".encode()
        preview = self.snapshots.capture(source_id)
        self.review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
        self.n += 1
        assert self.ingestion.ingest(preview.version_id, f"k{self.n}").status == "completed"
        return preview.version_id

    def chunk_id(self, version_id):
        with self.db.connect() as c:
            return c.execute("SELECT id FROM chunks WHERE version_id=?", (version_id,)).fetchone()[
                0
            ]

    def count(self, sql, *args):
        with self.db.connect() as c:
            return c.execute(sql, args).fetchone()[0]


@pytest.fixture
def world(db, tmp_path):
    return World(db, tmp_path)


def draft(chunk_id, quote="starts with an application", status="partial"):
    return AnswerDraft.model_validate(
        {
            "evidence_status": status,
            "claims": [
                {
                    "claim_id": "c1",
                    "kind": "fact",
                    "text": "It starts with an application.",
                    "evidence": [{"chunk_id": chunk_id, "support_quote": quote}],
                }
            ],
            "limitations": ["Synthetic."],
            "missing_evidence": []
            if status == "answered"
            else [
                {
                    "reason_type": "needs_external_validation",
                    "subquestion": "When?",
                    "needed_evidence": "A dated offer.",
                    "suggested_queries": ["NZ offer"],
                }
            ],
        }
    )


class Scripted:
    """Returns or raises the scripted results in order; records repair notes."""

    def __init__(self, *results, before=None):
        self.results = list(results)
        self.repairs = []
        self.before = before
        self.last = SimpleNamespace(
            model="model-x",
            requested_model="model-x",
            output_mode="schema",
            registration_ref="abc123",
            usage={"output_tokens": 5},
            request_id="req-1",
        )

    def generate(self, question, context, repair=None):
        self.repairs.append(repair)
        if self.before:
            self.before()
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def ask(world, provider, key="op-1", question="How does the process start?", **filters):
    return world.service.ask(question, RetrievalFilters(**filters), key, provider)


def test_verified_answer_is_saved_with_server_side_citations(world):
    version = world.publish()
    envelope = ask(world, FakeAnswerProvider())
    assert envelope.execution_status == "completed" and envelope.evidence_status == "partial"
    [citation] = envelope.citations
    assert citation["number"] == 1 and citation["claim_ids"] == ["c1"]
    assert citation["source"]["title"] == "guide title"
    assert citation["source"]["original_url"] == "https://synthetic.example/guide"
    assert citation["source"]["version_id"] == version
    assert citation["locator"]["paragraph_index"] == 1
    assert world.count("SELECT COUNT(*) FROM citations") == 1
    with world.db.connect() as c:
        row = c.execute("SELECT * FROM qa_records").fetchone()
    assert (row["output_mode"], row["model_id"]) == ("fixture", "synthetic-fixture")
    assert json.loads(row["context_version_ids_json"]) == [version]
    assert json.loads(row["answer_json"])["draft"]["claims"][0]["claim_id"] == "c1"


def test_fabricated_citation_is_repaired_once_then_published(world):
    version = world.publish()
    good = draft(world.chunk_id(version))
    provider = Scripted(draft("made-up-chunk"), good)
    envelope = ask(world, provider)
    assert envelope.execution_status == "completed"
    assert provider.repairs[0] is None and "made-up-chunk" in provider.repairs[1]
    usage = json.loads(world.count("SELECT usage_json FROM qa_records"))
    assert usage["attempts"] == 2 and usage["request_id"] == "req-1"
    assert world.count("SELECT output_mode FROM qa_records") == "schema"


@pytest.mark.parametrize("bad", ["made-up-chunk", "wrong-quote"])
def test_unfixable_citations_fail_without_publishing(world, bad):
    version = world.publish()
    chunk = world.chunk_id(version)
    first = draft("made-up-chunk") if bad == "made-up-chunk" else draft(chunk, "not in the text")
    envelope = ask(world, Scripted(first, first))
    assert envelope.execution_status == "failed"
    assert envelope.error == {"code": "CITATION_INVALID"}
    assert envelope.claims == [] and envelope.evidence_status is None
    assert world.count("SELECT COUNT(*) FROM citations") == 0
    assert world.count("SELECT answer_json FROM qa_records") is None


def test_format_error_is_repaired_once_and_second_failure_is_saved(world):
    version = world.publish()
    good = draft(world.chunk_id(version))
    repaired = ask(world, Scripted(AppError("OUTPUT_INVALID", "x"), good), key="op-a")
    assert repaired.execution_status == "completed"
    failed = ask(
        world,
        Scripted(AppError("OUTPUT_INVALID", "x"), AppError("OUTPUT_INVALID", "x")),
        key="op-b",
    )
    assert failed.execution_status == "failed" and failed.error == {"code": "OUTPUT_INVALID"}


@pytest.mark.parametrize(
    "code", ["USAGE_LIMITED", "STREAM_INCOMPLETE", "PROVIDER_TIMEOUT", "PLAN_PERMISSION_MISSING"]
)
def test_provider_failures_are_failures_not_insufficient_evidence(world, code):
    world.publish()
    provider = Scripted(AppError(code, "x"), AppError(code, "x"))
    envelope = ask(world, provider)
    assert len(provider.repairs) == 1  # never retried
    assert envelope.execution_status == "failed" and envelope.error == {"code": code}
    assert envelope.evidence_status is None and envelope.missing_evidence == []


def test_source_revoked_during_generation_gives_stale_context(world):
    version = world.publish()
    revoke = lambda: world.review.revoke(version, "Researcher", "Withdrawn")  # noqa: E731
    envelope = ask(world, Scripted(draft(world.chunk_id(version)), before=revoke))
    assert envelope.execution_status == "stale_context"
    assert envelope.claims == [] and envelope.error == {"code": "STALE_CONTEXT"}
    assert world.count("SELECT COUNT(*) FROM citations") == 0


def test_empty_library_or_excluded_scope_is_insufficient_without_a_model(world):
    provider = FakeAnswerProvider()
    empty = ask(world, provider, key="op-empty")
    assert empty.execution_status == "completed" and empty.evidence_status == "insufficient"
    assert empty.missing_evidence[0].reason_type == "no_evidence"
    world.publish(jurisdiction="US")
    excluded = ask(world, provider, key="op-nz", region="NZ")
    assert excluded.missing_evidence[0].reason_type == "jurisdiction_mismatch"
    assert provider.calls == 0


def test_operation_key_replay_never_calls_the_model_again(world):
    world.publish()
    provider = FakeAnswerProvider()
    first = ask(world, provider)
    assert ask(world, provider) == first
    assert provider.calls == 1
    failing = Scripted(AppError("USAGE_LIMITED", "x"))
    failed = ask(world, failing, key="op-fail")
    assert ask(world, failing, key="op-fail") == failed
    assert len(failing.repairs) == 1
    assert world.count("SELECT COUNT(*) FROM qa_records") == 2


def test_missing_provider_is_a_failure(world):
    world.publish()
    envelope = ask(world, None)
    assert envelope.execution_status == "failed" and envelope.error == {"code": "AUTH_REQUIRED"}


def test_save_failure_rolls_back_the_whole_answer(world):
    world.publish()
    with world.db.transaction() as c:
        c.execute(
            "CREATE TRIGGER no_citations BEFORE INSERT ON citations "
            "BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
        )
    with pytest.raises(AppError) as raised:
        ask(world, FakeAnswerProvider())
    assert raised.value.code == "QA_SAVE_FAILED"
    assert world.count("SELECT COUNT(*) FROM qa_records") == 0


def test_history_keeps_the_cited_version_after_a_new_edition(world):
    old = world.publish()
    first = ask(world, FakeAnswerProvider(), key="op-old")
    with world.db.connect() as c:
        source_id = c.execute(
            "SELECT source_id FROM document_versions WHERE id=?", (old,)
        ).fetchone()[0]
    new = world.revise(source_id, "https://synthetic.example/guide", TEXT + " Revised.")
    assert new != old
    assert world.service.replay("op-old") == first
    with world.db.connect() as c:
        stored = json.loads(
            c.execute("SELECT source_metadata_snapshot_json FROM citations").fetchone()[0]
        )
    assert stored["version_id"] == old
