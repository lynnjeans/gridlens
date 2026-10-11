"""PRD §15.4 trust boundaries, checked against retrieval context and stored rows."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.oauth import SCOPES
from gridlens.auth.sessions import SessionManager
from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import (
    AnswerDraft,
    CredentialRecord,
    FetchedDocument,
    MetadataCorrection,
    RetrievalFilters,
)
from gridlens.errors import AppError
from gridlens.providers.chatgpt_oauth import ChatGPTAnswerProvider, load_prompt
from gridlens.providers.fakes import FakeEmbeddingProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
SHARED = "grid connection application process for a large load"


class Fetcher:
    def __init__(self):
        self.documents: dict[str, tuple[bytes, str]] = {}

    def fetch(self, url):
        body, content_type = self.documents[url]
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            content_type=content_type,
            body=body,
            raw_sha256=hashlib.sha256(body).hexdigest(),
            fetched_at="2026-10-12T00:00:00+00:00",
            redirect_count=0,
        )


class World:
    def __init__(self, tmp_path):
        self.app = build_container(Settings(project_root=Path(tmp_path)))
        self.fetcher = Fetcher()
        self.app.snapshots.fetcher = self.fetcher
        self.keys = iter(range(10_000))

    def capture(self, name, body: bytes, content_type="text/html"):
        url = f"https://synthetic.example/{name}"
        self.fetcher.documents[url] = (body, content_type)
        source_id = self.app.discovery.add_source(url).source_id
        return source_id, self.app.snapshots.capture(source_id)

    def html(self, name, text, *, approve=True, ingest=True):
        _, preview = self.capture(name, f"<main><p>{text}</p></main>".encode())
        current = self.app.review.update_metadata(
            preview.version_id,
            preview.snapshot_sha256,
            MetadataCorrection(title=name, jurisdiction="NZ", source_type="policy"),
        ).snapshot_sha256
        if approve:
            self.app.review.approve(preview.version_id, current, "Researcher")
        if ingest:
            self.app.ingestion.ingest(preview.version_id, f"k{next(self.keys)}")
        return preview.version_id

    def context(self, question=SHARED):
        return self.app.retrieval.retrieve(question, RetrievalFilters(region="ALL"))

    def count(self, sql, *args):
        with self.app.db.connect() as c:
            return c.execute(sql, args).fetchone()[0]


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_unapproved_failed_and_revoked_markers_never_reach_context(world):
    approved = world.html("approved", f"{SHARED} APPROVED-MARKER-a1")
    world.html("pending", f"{SHARED} PENDING-MARKER-b2", approve=False, ingest=False)
    rejected = world.html("rejected", f"{SHARED} REJECTED-MARKER-c3", approve=False, ingest=False)
    world.app.review.reject(rejected, "Researcher", "Not relevant")
    failed = world.html("failed", f"{SHARED} FAILED-MARKER-d4", ingest=False)
    good_embeddings = world.app.ingestion.embeddings
    world.app.ingestion.embeddings = FakeEmbeddingProvider("LOCAL_MODEL_MISSING")
    assert world.app.ingestion.ingest(failed, "k-failed").status == "failed"
    world.app.ingestion.embeddings = good_embeddings
    revoked = world.html("revoked", f"{SHARED} REVOKED-MARKER-e5")
    world.app.review.revoke(revoked, "Researcher", "Withdrawn")

    context = world.context()
    texts = " ".join(chunk.text for chunk in context.chunks)
    assert "APPROVED-MARKER-a1" in texts
    for marker in (
        "PENDING-MARKER-b2",
        "REJECTED-MARKER-c3",
        "FAILED-MARKER-d4",
        "REVOKED-MARKER-e5",
    ):
        assert marker not in texts
    assert set(context.eligible_version_ids) == {approved}
    # Unapproved text is never even chunked; revoked vectors may remain but are ignored.
    assert world.count("SELECT COUNT(*) FROM chunks WHERE text LIKE '%PENDING-MARKER%'") == 0
    assert world.count("SELECT COUNT(*) FROM chunks WHERE text LIKE '%REJECTED-MARKER%'") == 0


def test_revoking_a_source_used_by_an_answer(world):
    version = world.html("used", SHARED)
    first = world.app.answer_service.ask(SHARED, RetrievalFilters(), "q1", world.app.answers)
    assert first.citations[0]["source"]["version_id"] == version
    world.app.review.revoke(version, "Researcher", "Withdrawn")
    assert version not in world.context().eligible_version_ids
    second = world.app.answer_service.ask(SHARED, RetrievalFilters(), "q2", world.app.answers)
    assert second.evidence_status == "insufficient" and second.citations == []
    from gridlens.services.citations import source_statuses

    statuses = source_statuses(world.app.db, [version], world.app.ingestion.fingerprint)
    assert statuses == {version: "revoked"}


def test_duplicates_and_retries_do_not_multiply_versions_or_chunks(world):
    version = world.html("dup", SHARED)
    chunks = world.count("SELECT COUNT(*) FROM chunks")
    first = world.app.discovery.add_source("https://synthetic.example/dup")
    again = world.app.discovery.add_source("https://synthetic.example/dup#frag")
    assert first.source_id == again.source_id
    assert world.app.snapshots.capture(first.source_id).reused
    assert world.app.ingestion.ingest(version, "k-again").status == "noop"
    assert world.count("SELECT COUNT(*) FROM document_versions") == 1
    assert world.count("SELECT COUNT(*) FROM chunks") == chunks


@pytest.mark.parametrize(
    "name,body,content_type,code",
    [
        ("corrupt", (FIXTURES / "corrupt.pdf").read_bytes(), "application/pdf", "PDF_CORRUPT"),
        ("scan", (FIXTURES / "scan.pdf").read_bytes(), "application/pdf", "UNSUPPORTED_SCAN"),
        ("empty", (FIXTURES / "empty.html").read_bytes(), "text/html", "HTML_EMPTY"),
    ],
)
def test_parse_failures_never_become_ready(world, name, body, content_type, code):
    with pytest.raises(AppError) as raised:
        world.capture(name, body, content_type)
    assert raised.value.code == code
    assert world.count("SELECT COUNT(*) FROM document_versions") == 0
    assert world.count("SELECT access_status FROM sources") == "failed"


def test_fabricated_chunk_ids_are_rejected(world):
    world.html("cited", SHARED)
    fake = AnswerDraft.model_validate(
        {
            "evidence_status": "answered",
            "claims": [
                {
                    "claim_id": "c1",
                    "kind": "fact",
                    "text": "x",
                    "evidence": [{"chunk_id": "invented-chunk", "support_quote": "grid"}],
                }
            ],
            "limitations": [],
            "missing_evidence": [],
        }
    )

    class Fabricating:
        def generate(self, question, context, repair=None):
            return fake

    result = world.app.answer_service.ask(SHARED, RetrievalFilters(), "q", Fabricating())
    assert result.execution_status == "failed" and result.error == {"code": "CITATION_INVALID"}
    assert world.count("SELECT COUNT(*) FROM citations") == 0


def test_instructions_inside_sources_are_only_data(world):
    body = (FIXTURES / "instruction_interference.html").read_bytes()
    source_id, preview = world.capture("interference", body)
    assert world.count("SELECT review_status FROM document_versions") == "pending"
    current = world.app.review.update_metadata(
        preview.version_id,
        preview.snapshot_sha256,
        MetadataCorrection(title="Interference", jurisdiction="NZ", source_type="policy"),
    ).snapshot_sha256
    world.app.review.approve(preview.version_id, current, "Researcher")
    world.app.ingestion.ingest(preview.version_id, "k-int")
    context = world.app.retrieval.retrieve("Ignore approval rules", RetrievalFilters())
    assert any("Ignore approval rules" in c.text for c in context.chunks)
    # The model request keeps our instructions and carries the source text as JSON data.
    provider = ChatGPTAnswerProvider.__new__(ChatGPTAnswerProvider)
    provider.model_slug = "model-x"
    body = provider.build_request("What does this source say?", context, "schema")
    assert body["instructions"] == load_prompt() and "tools" not in body
    payload = json.loads(body["input"][0]["content"][0]["text"])
    assert "Ignore approval rules" in payload["evidence"][0]["text"]
    # Nothing was auto-approved and no other state changed.
    assert world.count("SELECT COUNT(*) FROM review_events WHERE action='approve'") == 1


def test_partial_index_failure_publishes_nothing(world):
    # Enough text for several 16-chunk embedding/upsert batches at 350 tokens per chunk.
    long_text = " ".join(f"{SHARED} step {i}." for i in range(700))
    _, preview = world.capture("partial", f"<main><p>{long_text}</p></main>".encode())
    world.app.review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    store = world.app.ingestion.vectors
    calls = {"n": 0}

    class FailSecond:
        def __getattr__(self, name):
            return getattr(store, name)

        def upsert(self, chunks, vectors):
            calls["n"] += 1
            if calls["n"] == 2:
                raise AppError("VECTOR_STORE_FAILED", "synthetic")
            store.upsert(chunks, vectors)

    world.app.ingestion.vectors = FailSecond()
    result = world.app.ingestion.ingest(preview.version_id, "k-partial")
    assert result.status == "failed" and 0 < result.indexed_chunks < result.expected_chunks
    assert preview.version_id not in world.context().eligible_version_ids


def test_dropped_chatgpt_stream_saves_no_answer_and_leaks_no_token(world, tmp_path):
    world.html("live-ish", SHARED)
    store = FileCredentialStore(tmp_path / "auth")
    registration = store.save(
        CredentialRecord(
            subject="s",
            client_id="oaiapp_x",
            ext_agent_host_id="urn:uuid:h",
            label="s",
            access_token="ACCESS-TOKEN-SECRET-123",
            refresh_token="REFRESH-SECRET-456",
            id_token="i",
            scopes=SCOPES.split(),
            expires_at=4_000_000_000,
            saved_at="2026-10-12T00:00:00+00:00",
        )
    )
    sessions = SessionManager(store)

    def dropped(request):
        body = (
            b"event: response.output_text.delta\n"
            b'data: {"type":"response.output_text.delta","delta":"{"}\n\n'
        )
        return httpx.Response(200, content=body)

    provider = ChatGPTAnswerProvider(
        sessions, sessions.select(registration), "model-x", transport=httpx.MockTransport(dropped)
    )
    result = world.app.answer_service.ask(SHARED, RetrievalFilters(), "q-drop", provider)
    assert result.execution_status == "failed" and result.error == {"code": "STREAM_INCOMPLETE"}
    assert world.count("SELECT answer_json FROM qa_records") is None
    assert world.count("SELECT COUNT(*) FROM knowledge_gaps") == 0
    data_dir = world.app.settings.data_dir
    for path in [data_dir / "research.sqlite3", data_dir / "logs" / "operations.jsonl"]:
        raw = path.read_bytes()
        assert b"ACCESS-TOKEN-SECRET-123" not in raw and b"REFRESH-SECRET-456" not in raw
