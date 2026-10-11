"""Deterministic synthetic providers; never a live-provider fallback."""

import hashlib
import math
import re
from typing import Literal

from gridlens.contracts import (
    AnswerDraft,
    ChunkDTO,
    EmbeddingBatch,
    FetchedDocument,
    RetrievalContext,
    SearchHitDTO,
    VectorHit,
)
from gridlens.errors import AppError


class FakeSearchProvider:
    def __init__(self, fault: str | None = None):
        self.fault = fault
        self.calls = 0

    def search(self, query: str, limit: int) -> list[SearchHitDTO]:
        self.calls += 1
        if self.fault:
            raise AppError(self.fault, "Synthetic search failure.")
        if not query.strip():
            raise AppError("INVALID_INPUT", "Enter a research topic.")
        return [
            SearchHitDTO(
                title="Synthetic connection guide — not a real policy",
                url="https://synthetic.example/connection-guide",
                snippet="Synthetic material for testing approval and citations.",
                provider_rank=1,
                publisher="Synthetic publisher",
                source_type="technical",
                jurisdiction="NZ",
                metadata_evidence={"synthetic": True},
            )
        ][:limit]


SYNTHETIC_DOCUMENTS = {
    "https://synthetic.example/connection-guide": (
        b"<!doctype html><html><head><title>Synthetic connection guide</title></head>"
        b"<body><main><h1>Synthetic connection guide \xe2\x80\x94 not a real policy</h1>"
        b"<p>The synthetic process starts with an application.</p>"
        b"<h2>Review</h2><p>The synthetic request is reviewed by a fictional operator.</p>"
        b"<p>Missing project information must be recorded as a research gap.</p>"
        b"</main></body></html>"
    ),
    "https://synthetic.example/empty": b"<!doctype html><html><body><main></main></body></html>",
}


class FakeDocumentFetcher:
    """Serves synthetic HTML only; fixture mode never reaches a real host."""

    def __init__(self, documents: dict[str, bytes] | None = None):
        self.documents = SYNTHETIC_DOCUMENTS if documents is None else documents
        self.calls = 0

    def fetch(self, url: str) -> FetchedDocument:
        self.calls += 1
        body = self.documents.get(url.strip())
        if body is None:
            raise AppError("SOURCE_NOT_FOUND", "No synthetic document exists for this URL.")
        return FetchedDocument(
            requested_url=url,
            final_url=url.strip(),
            content_type="text/html",
            body=body,
            raw_sha256=hashlib.sha256(body).hexdigest(),
            fetched_at="2026-01-01T00:00:00+00:00",
            redirect_count=0,
        )


FAKE_TOKEN = re.compile(r"[\u3400-\u9fff]|(?:(?![\u3400-\u9fff])\w)+|[^\w\s]")


class FakeTokenizer:
    """Deterministic word/CJK-character tokenizer with two special tokens."""

    special_tokens = 2

    def count_tokens(self, texts: list[str]) -> list[int]:
        return [len(FAKE_TOKEN.findall(text)) + self.special_tokens for text in texts]

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        return [match.span() for match in FAKE_TOKEN.finditer(text)]


class FakeEmbeddingProvider:
    model_id = "synthetic-hash-16"
    revision = "fixture-v1"

    def identity(self) -> dict:
        return {"model_id": self.model_id, "revision": self.revision, "dimensions": 16}

    def __init__(self, fault: str | None = None):
        self.fault = fault

    def embed(self, texts: list[str], role: Literal["document", "query"]) -> EmbeddingBatch:
        if self.fault:
            raise AppError(self.fault, "Synthetic embedding failure.")
        if not texts or any(not t.strip() for t in texts):
            raise AppError("INVALID_INPUT", "Embedding inputs must be nonempty.")
        vectors = []
        for text in texts:
            v = [0.0] * 16
            for word in text.casefold().split():
                v[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 16] += 1
            length = math.sqrt(sum(n * n for n in v))
            vectors.append([n / length for n in v])
        return EmbeddingBatch(
            vectors=vectors,
            model_id=self.model_id,
            revision=self.revision,
            dimensions=16,
            role=role,
            local_token_count=sum(len(t.split()) for t in texts),
            latency_ms=0,
        )


class FakeAnswerProvider:
    def __init__(self, fault: str | None = None):
        self.fault = fault
        self.calls = 0
        self.repairs: list[str | None] = []

    def generate(
        self, question: str, context: RetrievalContext, repair: str | None = None
    ) -> AnswerDraft:
        self.calls += 1
        self.repairs.append(repair)
        if self.fault and self.fault != "CITATION_INVALID":
            raise AppError(self.fault, "Synthetic answer failure.")
        missing = {
            "reason_type": "needs_external_validation",
            "subquestion": question,
            "needed_evidence": "Real public sources, approved by a human.",
            "suggested_queries": [question],
        }
        claims = []
        if context.chunks:
            chunk = context.chunks[0]
            quote = chunk.text[:200]
            claims = [
                {
                    "claim_id": "c1",
                    "kind": "fact",
                    "text": quote,
                    "evidence": [
                        {
                            "chunk_id": "not-in-context" if self.fault else chunk.chunk_id,
                            "support_quote": quote,
                        }
                    ],
                }
            ]
        return AnswerDraft.model_validate(
            {
                "evidence_status": "partial" if claims else "insufficient",
                "claims": claims,
                "limitations": ["Synthetic test output; not real grid research."],
                "missing_evidence": [missing],
            }
        )


class FakeVectorStore:
    def __init__(self):
        self.items: dict[str, tuple[ChunkDTO, list[float]]] = {}

    def upsert(self, chunks: list[ChunkDTO], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise AppError("INDEX_INCOMPLETE", "Chunks and vectors must match.")
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.items[chunk.chunk_id] = (chunk, vector)

    def query(
        self, vector: list[float], eligible_version_ids: list[str], k: int
    ) -> list[VectorHit]:
        hits = []
        for chunk, v in self.items.values():
            if chunk.version_id in eligible_version_ids:
                if len(vector) != len(v):
                    raise AppError("INDEX_CONFIG_MISMATCH", "Vector dimensions differ.")
                distance = 1 - sum(a * b for a, b in zip(vector, v, strict=True))
                hits.append(VectorHit(chunk_id=chunk.chunk_id, distance=distance))
        return sorted(hits, key=lambda h: (h.distance, h.chunk_id))[:k]

    def stored_ids(self, version_id: str) -> set[str]:
        return {i for i, (c, _) in self.items.items() if c.version_id == version_id}

    def delete_version(self, version_id: str) -> None:
        for i in self.stored_ids(version_id):
            del self.items[i]
