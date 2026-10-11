import hashlib
import math

import pytest

from gridlens.contracts import ChunkDTO, Locator
from gridlens.errors import AppError
from gridlens.providers.chroma_store import ChromaVectorStore

pytest.importorskip("chromadb")

FINGERPRINT = "f" * 64
DIMS = 4


def chunk(version_id, ordinal, fingerprint=FINGERPRINT):
    text = f"{version_id} chunk {ordinal}"
    return ChunkDTO(
        chunk_id=hashlib.sha256(f"{version_id}-{ordinal}-{fingerprint}".encode()).hexdigest(),
        version_id=version_id,
        ordinal=ordinal,
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        embedding_text=text,
        token_count=5,
        source_segment_ids=["html-0001"],
        locator=Locator(kind="html", paragraph_index=1),
        index_fingerprint=fingerprint,
    )


def unit(*values):
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def store(tmp_path, fingerprint=FINGERPRINT, dims=DIMS):
    return ChromaVectorStore(tmp_path / "chroma", fingerprint, dims)


@pytest.fixture(autouse=True)
def default_embedding_is_never_used(monkeypatch):
    from chromadb.utils import embedding_functions

    def forbidden(*args, **kwargs):
        raise AssertionError("Chroma's default embedding model must not run")

    monkeypatch.setattr(embedding_functions.DefaultEmbeddingFunction, "__call__", forbidden)


def seeded(tmp_path):
    vector_store = store(tmp_path)
    chunks = [chunk("v1", 0), chunk("v1", 1), chunk("v2", 0)]
    vectors = [unit(1, 0, 0, 0), unit(1, 1, 0, 0), unit(0, 0, 1, 0)]
    vector_store.upsert(chunks, vectors)
    return vector_store, chunks, vectors


def test_upsert_is_idempotent_and_persists_across_reopen(tmp_path):
    vector_store, chunks, vectors = seeded(tmp_path)
    vector_store.upsert(chunks, vectors)
    assert vector_store.stored_ids("v1") == {chunks[0].chunk_id, chunks[1].chunk_id}
    assert vector_store.stored_ids("v2") == {chunks[2].chunk_id}

    reopened = store(tmp_path)
    hits = reopened.query(unit(1, 0, 0, 0), ["v1", "v2"], 10)
    assert [h.chunk_id for h in hits][0] == chunks[0].chunk_id
    assert len(hits) == 3
    assert hits[0].distance == pytest.approx(0, abs=1e-5)


def test_query_only_returns_whitelisted_versions(tmp_path):
    vector_store, chunks, _ = seeded(tmp_path)
    hits = vector_store.query(unit(1, 0, 0, 0), ["v2"], 10)
    assert [h.chunk_id for h in hits] == [chunks[2].chunk_id]
    assert vector_store.query(unit(1, 0, 0, 0), ["unknown"], 10) == []


@pytest.mark.parametrize("whitelist", [[], [""]])
def test_empty_whitelist_never_searches_everything(tmp_path, whitelist):
    vector_store, _, _ = seeded(tmp_path)
    assert vector_store.query(unit(1, 0, 0, 0), whitelist, 10) == []


def test_delete_version_removes_only_that_version(tmp_path):
    vector_store, chunks, _ = seeded(tmp_path)
    vector_store.delete_version("v1")
    assert vector_store.stored_ids("v1") == set()
    assert vector_store.stored_ids("v2") == {chunks[2].chunk_id}
    assert store(tmp_path).query(unit(1, 0, 0, 0), ["v1"], 10) == []


def test_metadata_holds_identifiers_only(tmp_path):
    vector_store, chunks, _ = seeded(tmp_path)
    record = vector_store._open().get(ids=[chunks[0].chunk_id], include=["metadatas", "documents"])
    assert record["metadatas"][0] == {
        "version_id": "v1",
        "ordinal": 0,
        "index_fingerprint": FINGERPRINT,
    }
    assert record["documents"] == [None]


def test_configuration_mismatches_are_explicit(tmp_path):
    vector_store, _, _ = seeded(tmp_path)
    with pytest.raises(AppError) as raised:
        vector_store.upsert([chunk("v3", 0, fingerprint="e" * 64)], [unit(1, 0, 0, 0)])
    assert raised.value.code == "INDEX_CONFIG_MISMATCH"
    with pytest.raises(AppError) as raised:
        vector_store.query([1.0, 0.0], ["v1"], 5)
    assert raised.value.code == "INDEX_CONFIG_MISMATCH"
    with pytest.raises(AppError) as raised:
        store(tmp_path, dims=8).query(unit(*([1.0] * 8)), ["v1"], 5)
    assert raised.value.code == "INDEX_CONFIG_MISMATCH"
    other = store(tmp_path, fingerprint="e" * 64)
    assert other.collection_name != vector_store.collection_name
    assert other.query(unit(1, 0, 0, 0), ["v1"], 5) == []


def test_invalid_writes_are_rejected(tmp_path):
    vector_store = store(tmp_path)
    with pytest.raises(AppError) as raised:
        vector_store.upsert([chunk("v1", 0)], [])
    assert raised.value.code == "INDEX_INCOMPLETE"
    with pytest.raises(AppError) as raised:
        vector_store.upsert([chunk("v1", 0)], [[float("nan"), 0, 0, 0]])
    assert raised.value.code == "INDEX_INCOMPLETE"
    with pytest.raises(AppError) as raised:
        vector_store.upsert([chunk("v1", 0), chunk("v1", 0)], [unit(1, 0, 0, 0)] * 2)
    assert raised.value.code == "INDEX_INCOMPLETE"


def test_construction_does_not_open_chroma(tmp_path):
    store(tmp_path)
    assert not (tmp_path / "chroma").exists()
