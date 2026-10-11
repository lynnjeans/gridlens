"""Deterministic token chunking of reviewed snapshot segments.

Rules (fixed by CHUNKER_VERSION):
- Consecutive segments are grouped by PDF file page or HTML heading path; chunks never
  cross a group, document or version.
- Whole segments are packed in order, joined by a blank line, while the embedding input
  (heading context + text, with special tokens) stays within the chunk budget.
- Only a single segment that alone exceeds the budget is split into token windows with
  the configured overlap. Windows are exact substrings cut at tokenizer offsets.
- Heading context longer than half the budget is left out of the embedding input; the
  heading path is still stored with the chunk.
"""

import hashlib
import json
from collections.abc import Iterator
from itertools import groupby

from gridlens.contracts import ChunkDTO, Locator, ParsedSegment, Tokenizer
from gridlens.errors import AppError

CHUNKER_VERSION = "segment-pack-v1"
SEGMENT_JOINER = "\n\n"
HEADING_JOINER = " > "


def canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def index_fingerprint(embedding_identity: dict, chunk_tokens: int, chunk_overlap: int) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "embedding": embedding_identity,
                "chunker_version": CHUNKER_VERSION,
                "chunk_tokens": chunk_tokens,
                "chunk_overlap": chunk_overlap,
            }
        )
    ).hexdigest()


def embedding_input(heading_path: list[str], text: str) -> str:
    return f"{HEADING_JOINER.join(heading_path)}{SEGMENT_JOINER}{text}" if heading_path else text


def chunk_segments(
    version_id: str,
    segments: list[ParsedSegment],
    tokenizer: Tokenizer,
    *,
    embedding_identity: dict,
    chunk_tokens: int,
    chunk_overlap: int,
    max_input_tokens: int,
) -> list[ChunkDTO]:
    if not 0 <= chunk_overlap < chunk_tokens <= max_input_tokens:
        raise AppError(
            "CHUNK_CONFIG_INVALID", "Chunk size must exceed overlap and fit the model limit."
        )
    if not version_id or not segments:
        raise AppError("CHUNK_INPUT_EMPTY", "There is no reviewed text to chunk.")
    chunker = _Chunker(tokenizer, chunk_tokens, chunk_overlap)
    fingerprint = index_fingerprint(embedding_identity, chunk_tokens, chunk_overlap)
    chunks = []
    for ordinal, (text, heading, context, segment_ids, locator) in enumerate(
        chunker.drafts(segments)
    ):
        model_input = embedding_input(context, text)
        token_count = chunker.count(model_input)
        if not text.strip() or token_count > chunk_tokens:
            raise AppError("CHUNK_INVALID", "A chunk is empty or exceeds the token budget.")
        text_sha256 = hashlib.sha256(text.encode()).hexdigest()
        chunk_id = hashlib.sha256(
            canonical_json([version_id, fingerprint, ordinal, text_sha256])
        ).hexdigest()
        chunks.append(
            ChunkDTO(
                chunk_id=chunk_id,
                version_id=version_id,
                ordinal=ordinal,
                text=text,
                text_sha256=text_sha256,
                embedding_text=model_input,
                heading_path=heading,
                token_count=token_count,
                source_segment_ids=segment_ids,
                locator=locator,
                index_fingerprint=fingerprint,
            )
        )
    return chunks


class _Chunker:
    def __init__(self, tokenizer: Tokenizer, size: int, overlap: int):
        self.tokenizer = tokenizer
        self.size = size
        self.overlap = overlap

    def count(self, text: str) -> int:
        return self.tokenizer.count_tokens([text])[0]

    def fits(self, context: list[str], text: str) -> bool:
        return self.count(embedding_input(context, text)) <= self.size

    def drafts(self, segments: list[ParsedSegment]) -> Iterator[tuple]:
        for _, group in groupby(segments, key=_group_key):
            group = list(group)
            heading = list(group[0].heading_path)
            # Heading context is optional model input; never let it starve the body.
            context = heading if self.count(embedding_input(heading, "")) <= self.size // 2 else []
            pending: list[ParsedSegment] = []
            for segment in group:
                if self.fits(context, _join(pending + [segment])):
                    pending.append(segment)
                    continue
                if pending:
                    yield self._packed(pending, heading, context)
                    pending = []
                if self.fits(context, segment.text):
                    pending = [segment]
                else:
                    yield from self._windows(segment, heading, context)
            if pending:
                yield self._packed(pending, heading, context)

    def _packed(self, segments, heading, context):
        locator = segments[0].locator
        if heading and locator.section_title is None:
            locator = Locator.model_validate({**locator.model_dump(), "section_title": heading[-1]})
        return (
            _join(segments),
            heading,
            context,
            [segment.segment_id for segment in segments],
            locator,
        )

    def _windows(self, segment: ParsedSegment, heading, context):
        offsets = self.tokenizer.token_offsets(segment.text)
        if not offsets:
            raise AppError("CHUNK_INVALID", "A reviewed segment produced no tokens.")
        budget = self.size - self.count(embedding_input(context, ""))
        if budget <= self.overlap:
            raise AppError("CHUNK_CONFIG_INVALID", "The chunk budget cannot exceed the overlap.")
        start = 0
        while True:
            end = min(start + budget, len(offsets))
            # Re-tokenizing a slice can differ slightly at its edges; shrink until it fits.
            while not self.fits(context, _slice(segment.text, offsets, start, end)):
                end -= 1
                if end - start <= self.overlap:
                    raise AppError("CHUNK_INVALID", "A token window could not fit the budget.")
            yield (
                _slice(segment.text, offsets, start, end),
                heading,
                context,
                [segment.segment_id],
                segment.locator,
            )
            if end == len(offsets):
                return
            start = end - self.overlap


def _group_key(segment: ParsedSegment):
    locator = segment.locator
    if locator.kind == "pdf":
        return ("pdf", locator.file_page)
    return ("html", tuple(segment.heading_path))


def _join(segments: list[ParsedSegment]) -> str:
    return SEGMENT_JOINER.join(segment.text for segment in segments)


def _slice(text: str, offsets: list[tuple[int, int]], start: int, end: int) -> str:
    return text[offsets[start][0] : offsets[end - 1][1]]
