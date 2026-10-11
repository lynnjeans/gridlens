import hashlib
import math
import sys
import types

import pytest

from gridlens.config import Settings
from gridlens.errors import AppError
from gridlens.providers.local_embeddings import (
    ALLOW_PATTERNS,
    MAX_BATCH,
    QUERY_PREFIX,
    LocalEmbeddingProvider,
    ModelManifest,
    manifest_path,
    prepare_model,
    sentence_transformer_loader,
)

REVISION = "a" * 40
DIMS = 384


class FakeTokenizer:
    def __call__(self, texts, *, add_special_tokens, truncation, verbose):
        assert add_special_tokens and not truncation
        return {"input_ids": [[0] * (len(t.split()) + 2) for t in texts]}


class FakeModel:
    def __init__(self, dims=DIMS, *, max_seq_length=12, fault=None):
        self.dims = dims
        self.max_seq_length = max_seq_length
        self.tokenizer = FakeTokenizer()
        self.fault = fault
        self.batches = []
        self.kwargs = []

    def get_sentence_embedding_dimension(self):
        return self.dims

    def encode(self, batch, **kwargs):
        self.batches.append(list(batch))
        self.kwargs.append(kwargs)
        rows = []
        for text in batch:
            seed = int(hashlib.sha256(text.encode()).hexdigest(), 16)
            row = [((seed >> (i % 200)) % 97) + 1.0 for i in range(self.dims)]
            norm = math.sqrt(sum(n * n for n in row))
            rows.append([n / norm for n in row])
        if self.fault == "nan":
            rows[0][0] = float("nan")
        if self.fault == "short":
            rows = rows[:-1]
        if self.fault == "unnormalized":
            rows[0] = [1.0] * self.dims
        return rows


def settings_for(tmp_path, **overrides):
    return Settings(project_root=tmp_path, **overrides)


def prepared(tmp_path, model=None, **overrides):
    settings = settings_for(tmp_path, **overrides)
    snapshot = settings.local_model_dir / "models--BAAI--bge-small-en-v1.5/snapshots" / REVISION
    snapshot.mkdir(parents=True)
    manifest_path(settings).write_text(
        ModelManifest(
            model_id=settings.embedding_model,
            revision=REVISION,
            tokenizer_revision=REVISION,
            snapshot_path=str(snapshot.relative_to(settings.local_model_dir)),
            dimensions=DIMS,
            max_seq_length=12,
            query_prefix=QUERY_PREFIX,
            document_prefix="",
            prepared_at="2026-10-11T00:00:00+00:00",
        ).model_dump_json()
    )
    model = model or FakeModel()
    loads = []

    def loader(path):
        loads.append(path)
        return model

    return LocalEmbeddingProvider(settings, loader=loader), model, loads


def test_missing_cache_and_revision_mismatch_fail_without_loading(tmp_path):
    loads = []
    provider = LocalEmbeddingProvider(settings_for(tmp_path), loader=loads.append)
    with pytest.raises(AppError) as raised:
        provider.embed(["grid connection"], "document")
    assert raised.value.code == "LOCAL_MODEL_MISSING"
    assert loads == []

    other, _, other_loads = prepared(tmp_path / "pinned", embedding_revision="b" * 40)
    with pytest.raises(AppError) as raised:
        other.embed(["grid connection"], "document")
    assert raised.value.code == "LOCAL_MODEL_MISSING"
    assert other_loads == []


def test_construction_does_not_load_model(tmp_path):
    _, _, loads = prepared(tmp_path)
    assert loads == []


def test_query_prefix_only_applies_to_queries_and_fingerprint_is_shared(tmp_path):
    provider, model, loads = prepared(tmp_path)
    document = provider.embed(["Connection study"], "document")
    query = provider.embed(["Connection study"], "query")
    assert model.batches == [["Connection study"], [QUERY_PREFIX + "Connection study"]]
    assert document.vectors != query.vectors
    assert document.role == "document" and query.role == "query"
    assert document.revision == query.revision == REVISION
    assert document.local_token_count == 4
    assert query.local_token_count == 4 + len(QUERY_PREFIX.split())
    assert len(loads) == 1
    assert all(
        kw["normalize_embeddings"] and kw["batch_size"] == MAX_BATCH and kw["convert_to_numpy"]
        for kw in model.kwargs
    )
    assert len(provider.fingerprint()) == 64


def test_batches_preserve_order_and_are_reproducible(tmp_path):
    provider, model, _ = prepared(tmp_path)
    texts = [f"segment {i}" for i in range(MAX_BATCH * 2 + 3)]
    first = provider.embed(texts, "document")
    assert [len(b) for b in model.batches] == [MAX_BATCH, MAX_BATCH, 3]
    assert [t for b in model.batches for t in b] == texts
    second = provider.embed(texts, "document")
    assert first.vectors == second.vectors
    assert first.dimensions == DIMS and len(first.vectors) == len(texts)


@pytest.mark.parametrize("texts", [[], [""], ["  "], ["ok", "\n"]])
def test_empty_inputs_are_rejected(tmp_path, texts):
    provider, model, _ = prepared(tmp_path)
    with pytest.raises(AppError) as raised:
        provider.embed(texts, "document")
    assert raised.value.code == "INVALID_INPUT"
    assert model.batches == []


def test_too_long_input_is_rejected_before_encoding(tmp_path):
    provider, model, _ = prepared(tmp_path)
    # 10 words + 2 special tokens fits a 12-token limit as a document but not as a query.
    text = " ".join(["word"] * 10)
    assert provider.embed([text], "document")
    with pytest.raises(AppError) as raised:
        provider.embed([text], "query")
    assert raised.value.code == "EMBEDDING_INPUT_TOO_LONG"
    assert len(model.batches) == 1


@pytest.mark.parametrize(
    "fault,code",
    [
        ("nan", "EMBEDDING_INVALID"),
        ("short", "EMBEDDING_INVALID"),
        ("unnormalized", "EMBEDDING_INVALID"),
    ],
)
def test_invalid_model_output_is_not_a_batch(tmp_path, fault, code):
    provider, _, _ = prepared(tmp_path, FakeModel(fault=fault))
    with pytest.raises(AppError) as raised:
        provider.embed(["one", "two"], "document")
    assert raised.value.code == code


def test_wrong_dimension_model_is_rejected(tmp_path):
    provider, _, _ = prepared(tmp_path, FakeModel(dims=16))
    with pytest.raises(AppError) as raised:
        provider.embed(["one"], "document")
    assert raised.value.code == "EMBEDDING_DIMENSION_MISMATCH"


def test_default_loader_is_local_only_without_remote_code(tmp_path, monkeypatch):
    calls = []

    class SentenceTransformer:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=SentenceTransformer),
    )
    sentence_transformer_loader(tmp_path)
    assert calls == [
        (str(tmp_path), {"device": "cpu", "local_files_only": True, "trust_remote_code": False})
    ]


def test_prepare_model_records_resolved_commit(tmp_path):
    settings = settings_for(tmp_path)
    requests = []

    def downloader(**kwargs):
        requests.append(kwargs)
        snapshot = settings.local_model_dir / "models--x/snapshots" / REVISION
        snapshot.mkdir(parents=True)
        return str(snapshot)

    manifest = prepare_model(
        settings,
        downloader=downloader,
        loader=lambda path: FakeModel(max_seq_length=512),
        clock=lambda: "2026-10-11T00:00:00+00:00",
    )
    assert requests == [
        {
            "repo_id": "BAAI/bge-small-en-v1.5",
            "revision": None,
            "cache_dir": str(settings.local_model_dir),
            "allow_patterns": ALLOW_PATTERNS,
        }
    ]
    assert manifest.revision == manifest.tokenizer_revision == REVISION
    assert manifest.max_seq_length == 512 and manifest.dimensions == DIMS
    assert ModelManifest.model_validate_json(manifest_path(settings).read_text()) == manifest


def test_prepare_model_rejects_non_commit_and_wrong_dimension(tmp_path):
    settings = settings_for(tmp_path)

    def branch_downloader(**kwargs):
        path = settings.local_model_dir / "snapshots/main"
        path.mkdir(parents=True)
        return str(path)

    with pytest.raises(AppError):
        prepare_model(settings, downloader=branch_downloader, loader=lambda p: FakeModel())

    def commit_downloader(**kwargs):
        path = settings.local_model_dir / "snapshots" / REVISION
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    with pytest.raises(AppError) as raised:
        prepare_model(settings, downloader=commit_downloader, loader=lambda p: FakeModel(16))
    assert raised.value.code == "EMBEDDING_DIMENSION_MISMATCH"
    assert not manifest_path(settings).exists()


def test_model_directory_follows_settings(tmp_path):
    assert settings_for(tmp_path).local_model_dir == (tmp_path / "models").resolve()
    custom = Settings.from_env(tmp_path, {"LOCAL_MODEL_DIR": "cache/models"})
    assert custom.local_model_dir == (tmp_path / "cache/models").resolve()
