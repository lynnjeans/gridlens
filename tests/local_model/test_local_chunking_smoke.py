"""Chunking with the real prepared BGE tokenizer. Run with `pytest -m local_model`."""

import pytest

from gridlens.config import Settings
from gridlens.contracts import Locator, ParsedSegment
from gridlens.documents.chunking import chunk_segments
from gridlens.errors import AppError
from gridlens.providers.local_embeddings import LocalEmbeddingProvider, read_manifest

ENGLISH = " ".join(
    f"Step {i}: the applicant submits load forecasts, single-line diagrams and studies."
    for i in range(120)
)
CHINESE = "数据中心并网申请需要提交负荷预测、单线图和系统研究报告。" * 60


@pytest.fixture(scope="module")
def provider():
    settings = Settings.from_env()
    try:
        read_manifest(settings)
    except AppError:
        pytest.skip("Local model is not prepared; a skip is not a successful model check")
    return LocalEmbeddingProvider(settings)


@pytest.mark.local_model
def test_real_tokenizer_chunks_fit_budget_and_embed(provider):
    settings = provider.settings
    segments = [
        ParsedSegment(
            segment_id="html-0001",
            text="Short introduction.",
            heading_path=["Connection guide"],
            locator=Locator(kind="html", paragraph_index=1),
        ),
        ParsedSegment(
            segment_id="pdf-0002",
            text=ENGLISH,
            locator=Locator(kind="pdf", file_page=2),
        ),
        ParsedSegment(
            segment_id="pdf-0003",
            text=CHINESE,
            locator=Locator(kind="pdf", file_page=3),
        ),
    ]
    chunks = chunk_segments(
        "version-1",
        segments,
        provider,
        embedding_identity=provider.identity(),
        chunk_tokens=settings.chunk_tokens,
        chunk_overlap=settings.chunk_overlap,
        max_input_tokens=provider.manifest.max_seq_length,
    )
    by_segment = {s.segment_id: s.text for s in segments}
    assert len([c for c in chunks if c.source_segment_ids == ["pdf-0002"]]) > 1
    assert len([c for c in chunks if c.source_segment_ids == ["pdf-0003"]]) > 1
    for c in chunks:
        assert c.token_count <= settings.chunk_tokens
        assert provider.count_tokens([c.embedding_text])[0] == c.token_count
        assert all(c.text in by_segment[sid] or sid == "html-0001" for sid in c.source_segment_ids)
    batch = provider.embed([c.embedding_text for c in chunks], "document")
    assert len(batch.vectors) == len(chunks)
    print(f"chunks={len(chunks)} max_tokens={max(c.token_count for c in chunks)}")
