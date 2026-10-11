"""Approved-only retrieval: SQLite decides eligibility, Chroma only ranks within it."""

import json
from collections import Counter

from gridlens.contracts import (
    ChunkDTO,
    EmbeddingProvider,
    Locator,
    RetrievalContext,
    RetrievalFilters,
    VectorStore,
)
from gridlens.errors import AppError
from gridlens.repositories.research import ResearchRepository


class RetrievalService:
    def __init__(
        self,
        research: ResearchRepository,
        *,
        embeddings: EmbeddingProvider,
        vectors: VectorStore,
        index_fingerprint: str,
        top_k: int,
        context_k: int,
        max_context_tokens: int,
    ):
        self.research = research
        self.embeddings = embeddings
        self.vectors = vectors
        self.index_fingerprint = index_fingerprint
        self.top_k = top_k
        self.context_k = context_k
        self.max_context_tokens = max_context_tokens

    def retrieve(self, question: str, filters: RetrievalFilters) -> RetrievalContext:
        question = question.strip()
        if not 3 <= len(question) <= 2000:
            raise AppError("INVALID_INPUT", "Ask a question between 3 and 2000 characters.")
        eligible, diagnostics = self._eligible(filters)
        if not eligible:
            # No eligible evidence: neither the embedding model nor Chroma is called.
            return self._context([], [], filters, diagnostics)

        query = self.embeddings.embed([question], "query")
        hits = self.vectors.query(query.vectors[0], sorted(eligible), self.top_k)
        rows = self.research.chunks_by_ids([hit.chunk_id for hit in hits], self.index_fingerprint)
        ranked, dropped = [], 0
        for hit in hits:
            row = rows.get(hit.chunk_id)
            if row is None or row["version_id"] not in eligible:
                dropped += 1  # out of scope: unknown ID, another index or ineligible version
                continue
            ranked.append(row)
        diagnostics.update(vector_hits=len(hits), dropped_out_of_scope=dropped)

        selected = self._select(ranked, diagnostics)
        # Re-check eligibility right before handing context on; never substitute evidence.
        still_eligible, _ = self._eligible(filters)
        context = [row for row in selected if row["version_id"] in still_eligible]
        diagnostics["dropped_after_recheck"] = len(selected) - len(context)
        if selected and not context:
            diagnostics["reason"] = "stale_context"
        elif not context:
            diagnostics["reason"] = "no_relevant_chunks"
        return self._context(context, sorted(still_eligible), filters, diagnostics)

    def _eligible(self, filters: RetrievalFilters) -> tuple[set[str], dict]:
        approved = self.research.eligible_versions(self.index_fingerprint, jurisdiction=None)
        allowed_regions = filters.jurisdictions()
        allowed_types = set(filters.source_types)
        eligible, by_region, by_type = set(), Counter(), Counter()
        for version in approved:
            # Reviewed metadata frozen with the approved snapshot, not current source labels.
            metadata = json.loads(version["metadata_json"])
            region = metadata.get("jurisdiction", "UNKNOWN")
            source_type = metadata.get("source_type", "unknown")
            if allowed_regions is not None and region not in allowed_regions:
                by_region[region] += 1
            elif allowed_types and source_type not in allowed_types:
                by_type[source_type] += 1
            else:
                eligible.add(version["id"])
        diagnostics = {
            "approved_versions": len(approved),
            "eligible_versions": len(eligible),
            "excluded_by_region": dict(sorted(by_region.items())),
            "excluded_by_type": dict(sorted(by_type.items())),
        }
        if not approved:
            diagnostics["reason"] = "no_approved_sources"
        elif not eligible:
            diagnostics["reason"] = "filters_excluded_all"
        return eligible, diagnostics

    def _select(self, ranked: list[dict], diagnostics: dict) -> list[dict]:
        selected: list[dict] = []
        tokens = overlapping = over_budget = 0
        for row in ranked:
            if len(selected) == self.context_k:
                break
            if any(_overlaps(row, kept) for kept in selected):
                overlapping += 1  # keep the higher-ranked of adjacent overlapping windows
                continue
            if tokens + row["token_count"] > self.max_context_tokens:
                over_budget += 1
                continue
            selected.append(row)
            tokens += row["token_count"]
        diagnostics.update(
            skipped_overlapping=overlapping, skipped_over_budget=over_budget, context_tokens=tokens
        )
        return selected

    def _context(self, rows, eligible_ids, filters, diagnostics) -> RetrievalContext:
        chunks, legacy = [], 0
        for row in rows:
            segment_ids = json.loads(row["source_segment_ids_json"])
            if not segment_ids:
                legacy += 1  # indexed before provenance was stored; re-index to restore
                continue
            chunks.append(
                ChunkDTO(
                    chunk_id=row["id"],
                    version_id=row["version_id"],
                    ordinal=row["ordinal"],
                    text=row["text"],
                    text_sha256=row["text_sha256"],
                    # The model input is not stored; downstream evidence is `text` only.
                    embedding_text=row["text"],
                    heading_path=json.loads(row["heading_path_json"]),
                    token_count=row["token_count"],
                    source_segment_ids=segment_ids,
                    locator=Locator.model_validate_json(row["locator_json"]),
                    index_fingerprint=row["index_fingerprint"],
                )
            )
        if legacy:
            diagnostics["dropped_without_provenance"] = legacy
        return RetrievalContext(
            chunks=chunks,
            eligible_version_ids=list(eligible_ids),
            filters=filters.model_dump(mode="json"),
            index_fingerprint=self.index_fingerprint,
            diagnostics=diagnostics,
        )


def _overlaps(row: dict, kept: dict) -> bool:
    # Only token windows of one segment overlap; they are adjacent and share that segment.
    return (
        row["version_id"] == kept["version_id"]
        and abs(row["ordinal"] - kept["ordinal"]) == 1
        and bool(
            set(json.loads(row["source_segment_ids_json"]))
            & set(json.loads(kept["source_segment_ids_json"]))
        )
    )
