"""One trustworthy Q&A operation: retrieve → generate → verify citations → save once.

Answers are assembled from verified claims only (no uncited summary). Provider failures
are saved as failures, never as "insufficient evidence". Replaying an operation key
returns the stored result without calling the model again.
"""

import json
import sqlite3
import time
from collections.abc import Callable
from uuid import uuid4

from gridlens.contracts import (
    AnswerDraft,
    AnswerEnvelope,
    AnswerProvider,
    RetrievalContext,
    RetrievalFilters,
)
from gridlens.db import Database, now
from gridlens.errors import AppError
from gridlens.providers.chatgpt_oauth import PROMPT_VERSION
from gridlens.repositories.research import ResearchRepository
from gridlens.services.citations import citation_problems
from gridlens.services.retrieval import RetrievalService

# Extension point for T24: writes gap rows inside the QA transaction, returns gap dicts.
GapWriter = Callable[[sqlite3.Connection, str, str, dict, AnswerDraft], list[dict]]
REPAIRABLE = {"OUTPUT_INVALID"}
EMPTY_REASONS = {
    "no_approved_sources": "no_evidence",
    "filters_excluded_all": "jurisdiction_mismatch",
    "no_relevant_chunks": "no_evidence",
}


class AnswerService:
    def __init__(
        self,
        db: Database,
        research: ResearchRepository,
        retrieval: RetrievalService,
        *,
        mode: str,
        max_attempts: int = 2,
        gap_writer: GapWriter | None = None,
        clock=time.monotonic,
    ):
        self.db = db
        self.research = research
        self.retrieval = retrieval
        self.mode = mode
        self.max_attempts = max_attempts
        self.gap_writer = gap_writer
        self.clock = clock

    def ask(
        self,
        question: str,
        filters: RetrievalFilters,
        operation_key: str,
        provider: AnswerProvider | None,
    ) -> AnswerEnvelope:
        if not operation_key.strip():
            raise AppError("INVALID_INPUT", "An operation key is required.")
        if stored := self.replay(operation_key):
            return stored
        started = self.clock()
        question = question.strip()
        context = self.retrieval.retrieve(question, filters)
        record = _Record(question, filters, context)

        if not context.chunks:
            reason = context.diagnostics.get("reason")
            if reason == "stale_context":
                return self._save(operation_key, record.stale(), started)
            # No eligible evidence: answer "insufficient" without calling any model.
            draft = AnswerDraft(
                evidence_status="insufficient",
                claims=[],
                limitations=["No approved, indexed source matched this question and scope."],
                missing_evidence=[
                    {
                        "reason_type": EMPTY_REASONS.get(reason, "no_evidence"),
                        "subquestion": question,
                        "needed_evidence": "Public sources that a reviewer has approved.",
                        "suggested_queries": [question],
                    }
                ],
            )
            return self._save(operation_key, record.completed(draft, []), started)

        if provider is None:
            return self._save(operation_key, record.failed("AUTH_REQUIRED"), started)
        repair, attempts = None, 0
        while True:
            attempts += 1
            try:
                draft = provider.generate(question, context, repair=repair)
            except AppError as error:
                record.attempts(attempts, provider)
                if error.code in REPAIRABLE and attempts < self.max_attempts:
                    repair = "the output did not match the AnswerDraft format."
                    continue
                return self._save(operation_key, record.failed(error.code), started)
            record.attempts(attempts, provider)
            problems = citation_problems(draft, context)
            if not problems:
                break
            if attempts >= self.max_attempts:
                return self._save(operation_key, record.failed("CITATION_INVALID"), started)
            repair = "; ".join(problems[:5])

        # Re-check eligibility right before publishing; a revoked source voids the draft.
        cited_versions = {
            chunk.version_id
            for chunk in context.chunks
            if any(e.chunk_id == chunk.chunk_id for c in draft.claims for e in c.evidence)
        }
        eligible = {
            v["id"]: v
            for v in self.research.eligible_versions(context.index_fingerprint, jurisdiction=None)
        }
        if not cited_versions <= set(eligible):
            return self._save(operation_key, record.stale(), started)
        citations = _citations(draft, context, eligible)
        return self._save(operation_key, record.completed(draft, citations), started)

    def replay(self, operation_key: str) -> AnswerEnvelope | None:
        with self.db.connect() as c:
            row = c.execute(
                "SELECT * FROM qa_records WHERE operation_key=?", (operation_key,)
            ).fetchone()
            if row is None:
                return None
            gaps = []
            if self.gap_writer is not None:
                gaps = [
                    dict(g)
                    for g in c.execute("SELECT * FROM knowledge_gaps WHERE qa_id=?", (row["id"],))
                ]
        return _envelope(dict(row), self.mode, gaps)

    def _save(self, operation_key: str, record: "_Record", started: float) -> AnswerEnvelope:
        qa_id = str(uuid4())
        row = record.row(qa_id, operation_key, int((self.clock() - started) * 1000))
        gaps: list[dict] = []
        try:
            with self.db.transaction() as c:
                c.execute(
                    "INSERT INTO qa_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[k] for k in QA_COLUMNS),
                )
                c.executemany(
                    "INSERT INTO citations VALUES (?,?,?,?,?,?,?)",
                    [
                        (
                            str(uuid4()),
                            qa_id,
                            citation["claim_id"],
                            citation["chunk_id"],
                            citation["quote"],
                            json.dumps(citation["locator"], ensure_ascii=False),
                            json.dumps(citation["source"], ensure_ascii=False),
                        )
                        for citation in record.citation_rows
                    ],
                )
                if self.gap_writer is not None and record.draft is not None:
                    gaps = self.gap_writer(
                        c, qa_id, record.question, record.filters.model_dump(), record.draft
                    )
        except sqlite3.IntegrityError:
            # Same operation key saved by another tab: return that result, never a second one.
            if stored := self.replay(operation_key):
                return stored
            raise AppError("QA_SAVE_FAILED", "The answer could not be saved.") from None
        except sqlite3.Error:
            raise AppError("QA_SAVE_FAILED", "The answer could not be saved.") from None
        return _envelope(row, self.mode, gaps)


QA_COLUMNS = (
    "id",
    "operation_key",
    "question",
    "filters_json",
    "execution_status",
    "evidence_status",
    "answer_json",
    "context_chunk_ids_json",
    "context_version_ids_json",
    "model_id",
    "output_mode",
    "account_registration_ref",
    "prompt_version",
    "index_fingerprint",
    "created_at",
    "latency_ms",
    "usage_json",
    "error_code",
)


class _Record:
    def __init__(self, question: str, filters: RetrievalFilters, context: RetrievalContext):
        self.question = question
        self.filters = filters
        self.context = context
        self.status = "failed"
        self.draft: AnswerDraft | None = None
        self.citations: list[dict] = []
        self.citation_rows: list[dict] = []
        self.error_code: str | None = None
        self.meta = {
            "model_id": None,
            "output_mode": None,
            "account_registration_ref": None,
            "usage": {},
            "attempts": 0,
        }

    def attempts(self, count: int, provider) -> None:
        self.meta["attempts"] = count
        if not hasattr(provider, "last"):
            # Only the synthetic provider has no call record.
            self.meta.update(model_id="synthetic-fixture", output_mode="fixture")
            return
        last = provider.last
        if last is None:
            return  # refused before any request (e.g. no plan permission)
        self.meta.update(
            model_id=last.model or last.requested_model,
            output_mode=last.output_mode,
            account_registration_ref=last.registration_ref,
        )
        usage = dict(last.usage or {})
        usage["request_id"] = last.request_id
        self.meta["usage"] = usage

    def completed(self, draft: AnswerDraft, citations: list[dict]) -> "_Record":
        self.status, self.draft, self.citations = "completed", draft, citations
        by_chunk = {citation["chunk_id"]: citation for citation in citations}
        rows, seen = [], set()
        for claim in draft.claims:
            for evidence in claim.evidence:
                if (claim.claim_id, evidence.chunk_id) in seen:
                    continue
                seen.add((claim.claim_id, evidence.chunk_id))
                citation = by_chunk[evidence.chunk_id]
                rows.append(
                    {
                        "claim_id": claim.claim_id,
                        "chunk_id": evidence.chunk_id,
                        "quote": evidence.support_quote,
                        "locator": citation["locator"],
                        "source": citation["source"],
                    }
                )
        self.citation_rows = rows
        return self

    def failed(self, code: str) -> "_Record":
        self.status, self.error_code = "failed", code
        return self

    def stale(self) -> "_Record":
        self.status, self.error_code = "stale_context", "STALE_CONTEXT"
        return self

    def row(self, qa_id: str, operation_key: str, latency_ms: int) -> dict:
        answer = (
            json.dumps(
                {"draft": self.draft.model_dump(mode="json"), "citations": self.citations},
                ensure_ascii=False,
            )
            if self.draft is not None
            else None
        )
        return {
            "id": qa_id,
            "operation_key": operation_key,
            "question": self.question,
            "filters_json": self.filters.model_dump_json(),
            "execution_status": self.status,
            "evidence_status": self.draft.evidence_status if self.draft else None,
            "answer_json": answer,
            "context_chunk_ids_json": json.dumps([c.chunk_id for c in self.context.chunks]),
            "context_version_ids_json": json.dumps(
                sorted({c.version_id for c in self.context.chunks})
            ),
            "model_id": self.meta["model_id"],
            "output_mode": self.meta["output_mode"],
            "account_registration_ref": self.meta["account_registration_ref"],
            "prompt_version": PROMPT_VERSION,
            "index_fingerprint": self.context.index_fingerprint,
            "created_at": now(),
            "latency_ms": latency_ms,
            "usage_json": json.dumps({**self.meta["usage"], "attempts": self.meta["attempts"]}),
            "error_code": self.error_code,
        }


def _citations(draft: AnswerDraft, context: RetrievalContext, eligible: dict) -> list[dict]:
    """Numbered by first appearance; titles, links and locations come from snapshots only."""
    chunks = {chunk.chunk_id: chunk for chunk in context.chunks}
    by_chunk: dict[str, dict] = {}
    for claim in draft.claims:
        for evidence in claim.evidence:
            entry = by_chunk.get(evidence.chunk_id)
            if entry is None:
                chunk = chunks[evidence.chunk_id]
                metadata = json.loads(eligible[chunk.version_id]["metadata_json"])
                entry = by_chunk[evidence.chunk_id] = {
                    "number": len(by_chunk) + 1,
                    "chunk_id": chunk.chunk_id,
                    "quote": evidence.support_quote,
                    "claim_ids": [],
                    "locator": {
                        **chunk.locator.model_dump(exclude_none=True),
                        "heading_path": chunk.heading_path,
                    },
                    "source": {
                        "version_id": chunk.version_id,
                        "snapshot_sha256": eligible[chunk.version_id]["snapshot_sha256"],
                        **{
                            key: metadata.get(key)
                            for key in (
                                "title",
                                "publisher",
                                "published_at",
                                "jurisdiction",
                                "source_type",
                                "original_url",
                                "final_url",
                            )
                        },
                    },
                }
            if claim.claim_id not in entry["claim_ids"]:
                entry["claim_ids"].append(claim.claim_id)
    return list(by_chunk.values())


def _envelope(row: dict, mode: str, gaps: list[dict]) -> AnswerEnvelope:
    answer = json.loads(row["answer_json"]) if row["answer_json"] else None
    draft = answer["draft"] if answer else None
    return AnswerEnvelope(
        qa_id=row["id"],
        execution_status=row["execution_status"],
        evidence_status=row["evidence_status"],
        claims=draft["claims"] if draft else [],
        limitations=draft["limitations"] if draft else [],
        missing_evidence=draft["missing_evidence"] if draft else [],
        citations=answer["citations"] if answer else [],
        gaps=gaps if row["execution_status"] == "completed" else [],
        error=(
            {"code": row["error_code"]}
            if row["execution_status"] != "completed" and row["error_code"]
            else None
        ),
        mode=mode,
    )
