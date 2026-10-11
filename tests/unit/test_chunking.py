import re

import pytest

from gridlens.contracts import Locator, ParsedSegment
from gridlens.documents.chunking import (
    CHUNKER_VERSION,
    chunk_segments,
    embedding_input,
    index_fingerprint,
)
from gridlens.errors import AppError
from gridlens.providers.fakes import FakeTokenizer

IDENTITY = {"model_id": "m", "revision": "r1", "dimensions": 384, "query_prefix": "q: "}
TOKENIZER = FakeTokenizer()


def html(index, text, heading=("Guide",)):
    return ParsedSegment(
        segment_id=f"html-{index:04d}",
        text=text,
        heading_path=list(heading),
        locator=Locator(kind="html", paragraph_index=index),
    )


def pdf(page, text):
    return ParsedSegment(
        segment_id=f"pdf-{page:04d}",
        text=text,
        locator=Locator(kind="pdf", file_page=page),
    )


def chunk(segments, *, size=30, overlap=5, identity=IDENTITY, version="v1"):
    return chunk_segments(
        version,
        segments,
        TOKENIZER,
        embedding_identity=identity,
        chunk_tokens=size,
        chunk_overlap=overlap,
        max_input_tokens=512,
    )


def words(n, stem="word"):
    return " ".join(f"{stem}{i}" for i in range(n))


def test_short_paragraphs_pack_within_one_section():
    segments = [html(1, "Apply first."), html(2, "Then wait for review.")]
    [only] = chunk(segments)
    assert only.text == "Apply first.\n\nThen wait for review."
    assert only.embedding_text == "Guide\n\nApply first.\n\nThen wait for review."
    assert only.source_segment_ids == ["html-0001", "html-0002"]
    assert only.locator.paragraph_index == 1 and only.locator.section_title == "Guide"
    assert only.token_count == TOKENIZER.count_tokens([only.embedding_text])[0]
    assert only.ordinal == 0 and only.version_id == "v1"


def test_chunks_never_cross_sections_or_pdf_pages():
    sections = chunk([html(1, "Intro."), html(2, "Costs.", heading=("Guide", "Costs"))])
    assert [c.heading_path for c in sections] == [["Guide"], ["Guide", "Costs"]]
    pages = chunk([pdf(1, "Page one."), pdf(2, "Page two."), pdf(3, "Page three.")])
    assert [c.locator.file_page for c in pages] == [1, 2, 3]
    assert [c.ordinal for c in pages] == [0, 1, 2]


def test_packing_stops_at_budget_and_keeps_order():
    segments = [html(i, words(8, f"p{i}w")) for i in range(1, 7)]
    chunks = chunk(segments, size=30)
    assert len(chunks) > 1
    assert [sid for c in chunks for sid in c.source_segment_ids] == [s.segment_id for s in segments]
    assert all(c.token_count <= 30 for c in chunks)


def test_long_paragraph_uses_overlapping_exact_windows():
    text = words(100)
    chunks = chunk([html(1, text)], size=30, overlap=5)
    assert len(chunks) > 3
    assert all(c.token_count <= 30 and c.text in text for c in chunks)
    tokens = [TOKENIZER.token_offsets(c.text) for c in chunks]
    for previous, current, prev_tokens in zip(chunks, chunks[1:], tokens, strict=False):
        tail = [previous.text[s:e] for s, e in prev_tokens[-5:]]
        head = [current.text[s:e] for s, e in TOKENIZER.token_offsets(current.text)[:5]]
        assert tail == head
    covered = set()
    for c in chunks:
        covered.update(c.text.split())
    assert covered == set(text.split())
    assert chunks[0].text.startswith("word0") and chunks[-1].text.endswith("word99")


def test_long_unicode_paragraph_remains_traceable_on_its_page():
    text = "并网申请需要提交负荷资料。" * 12 + " Grid connection review continues."
    chunks = chunk([pdf(4, "Short page."), pdf(5, text), pdf(6, "Next page.")], size=25)
    long = [c for c in chunks if c.source_segment_ids == ["pdf-0005"]]
    assert len(long) > 1
    assert all(c.locator.file_page == 5 and c.text in text for c in long)
    assert "".join(c.text for c in long).count("并") >= text.count("并")
    assert [c.locator.file_page for c in chunks] == sorted(c.locator.file_page for c in chunks)
    assert {c.locator.file_page for c in chunks} == {4, 5, 6}


def test_every_nonempty_segment_is_represented():
    segments = [
        html(1, "Short."),
        html(2, words(80)),
        html(3, "Tail note."),
        pdf(1, words(5, "pdf")),
    ]
    chunks = chunk(segments, size=30)
    represented = {sid for c in chunks for sid in c.source_segment_ids}
    assert represented == {s.segment_id for s in segments}
    for segment in segments:
        joined = " ".join(c.text for c in chunks if segment.segment_id in c.source_segment_ids)
        assert set(re.findall(r"\w+", segment.text)) <= set(re.findall(r"\w+", joined))


def test_ids_are_deterministic_and_change_with_version_or_config():
    segments = [html(1, words(50))]
    first, second = chunk(segments), chunk(segments)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len({c.chunk_id for c in first}) == len(first)
    assert {c.chunk_id for c in first}.isdisjoint(c.chunk_id for c in chunk(segments, version="v2"))
    base = first[0].index_fingerprint
    assert base == index_fingerprint(IDENTITY, 30, 5)
    variants = [
        index_fingerprint(IDENTITY, 31, 5),
        index_fingerprint(IDENTITY, 30, 6),
        index_fingerprint({**IDENTITY, "revision": "r2"}, 30, 5),
        index_fingerprint({**IDENTITY, "query_prefix": ""}, 30, 5),
        index_fingerprint({**IDENTITY, "tokenizer_revision": "t2"}, 30, 5),
        index_fingerprint({**IDENTITY, "normalize": False}, 30, 5),
    ]
    assert base not in variants and len(set(variants)) == len(variants)
    assert CHUNKER_VERSION


def test_long_heading_is_left_out_of_embedding_input_only():
    heading = (words(20, "h"),)
    [only] = chunk([html(1, "Body text.", heading=heading)], size=30)
    assert only.embedding_text == "Body text."
    assert only.heading_path == list(heading)


@pytest.mark.parametrize(
    "size,overlap,limit",
    [(30, 30, 512), (30, 40, 512), (600, 50, 512), (30, -1, 512)],
)
def test_invalid_configuration_is_rejected(size, overlap, limit):
    with pytest.raises(AppError) as raised:
        chunk_segments(
            "v1",
            [html(1, "Text.")],
            TOKENIZER,
            embedding_identity=IDENTITY,
            chunk_tokens=size,
            chunk_overlap=overlap,
            max_input_tokens=limit,
        )
    assert raised.value.code == "CHUNK_CONFIG_INVALID"


def test_empty_input_is_rejected():
    with pytest.raises(AppError) as raised:
        chunk([])
    assert raised.value.code == "CHUNK_INPUT_EMPTY"


def test_embedding_input_without_heading_is_the_text():
    assert embedding_input([], "Text.") == "Text."
    assert embedding_input(["A", "B"], "Text.") == "A > B\n\nText."
