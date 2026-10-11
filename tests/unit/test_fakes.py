import json
import socket

import pytest
from pypdf import PdfReader
from pytest_socket import SocketBlockedError

from gridlens.bootstrap import build_container
from gridlens.contracts import ChunkDTO, Locator, RetrievalContext
from gridlens.errors import AppError
from gridlens.providers.fakes import (
    FakeAnswerProvider,
    FakeEmbeddingProvider,
    FakeSearchProvider,
    FakeVectorStore,
)


def test_default_network_blocked():
    with pytest.warns(UserWarning), pytest.raises(SocketBlockedError):
        socket.socket()


def test_fake_deterministic_and_faults():
    assert FakeSearchProvider().search("connection", 10) == FakeSearchProvider().search(
        "connection", 10
    )
    embed = FakeEmbeddingProvider()
    assert embed.embed(["test document"], "document") == embed.embed(["test document"], "document")
    with pytest.raises(AppError) as e:
        FakeSearchProvider("RATE_LIMITED").search("test", 10)
    assert e.value.code == "RATE_LIMITED"
    with pytest.raises(AppError):
        embed.embed([""], "document")


def test_fake_answer_and_whitelist_vector_store():
    chunks = [
        ChunkDTO(
            chunk_id=f"c{i}",
            version_id=f"v{i}",
            ordinal=0,
            text="Synthetic application stage.",
            text_sha256="0" * 64,
            embedding_text="Synthetic application stage.",
            token_count=3,
            source_segment_ids=["p1"],
            locator=Locator(kind="html", paragraph_index=1),
            index_fingerprint="fixture",
        )
        for i in range(2)
    ]
    vectors = FakeEmbeddingProvider().embed([c.text for c in chunks], "document").vectors
    store = FakeVectorStore()
    store.upsert(chunks, vectors)
    store.upsert(chunks, vectors)
    assert store.stored_ids("v0") == {"c0"}
    assert [h.chunk_id for h in store.query(vectors[0], ["v1"], 10)] == ["c1"]
    context = RetrievalContext(
        chunks=chunks[:1], eligible_version_ids=["v0"], filters={}, index_fingerprint="fixture"
    )
    draft = FakeAnswerProvider().generate("question", context)
    assert draft.claims[0].evidence[0].support_quote in chunks[0].text
    assert (
        FakeAnswerProvider("CITATION_INVALID")
        .generate("question", context)
        .claims[0]
        .evidence[0]
        .chunk_id
        == "not-in-context"
    )
    store.delete_version("v0")
    assert not store.stored_ids("v0")


def test_live_boot_never_falls_back_to_fake(settings):
    live = settings.model_copy(
        update={"mode": "live", "data_dir": settings.project_root / "data/live"}
    )
    app = build_container(live)
    assert app.search is None and app.answers is None and app.embeddings is None
    assert not app.credentials.directory.exists()


def test_fixture_manifest(fixtures_dir):
    manifest = json.loads((fixtures_dir / "manifest.json").read_text())
    assert manifest["synthetic"] is True
    for item in manifest["pdfs"]:
        reader = PdfReader(fixtures_dir / item["file"])
        assert len(reader.pages) == item["pages"]
        for page, expected in zip(reader.pages, item["text_by_page"], strict=True):
            assert (page.extract_text() or "").strip() == expected
    for filename in manifest["files"]:
        assert (fixtures_dir / filename).is_file()


def test_synthetic_oauth_jwks_and_rotating_token_fixtures(fixtures_dir):
    import jwt

    oauth = json.loads((fixtures_dir / "scenarios.json").read_text())["oauth"]
    key = jwt.PyJWK.from_dict(oauth["jwks"]["keys"][0])
    claims = jwt.decode(
        oauth["id_token"],
        key.key,
        algorithms=["RS256"],
        audience=oauth["client_id"],
        issuer="https://auth.openai.com",
    )
    assert claims["nonce"] == oauth["nonce"]
    assert claims["sub"] == "synthetic-subject"
    assert oauth["token_response"]["refresh_token"] != oauth["rotated_response"]["refresh_token"]
    assert oauth["refresh_error"]["error"] == "invalid_grant"
