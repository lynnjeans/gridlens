"""Knowledge gaps from verified answers: deduplicated while open, closed only by people."""

import hashlib
import json
import re
import sqlite3
from uuid import uuid4

from gridlens.contracts import AnswerDraft, MissingEvidence
from gridlens.db import Database, now
from gridlens.errors import AppError

REASON_TYPES = {
    "no_evidence",
    "partial_coverage",
    "jurisdiction_mismatch",
    "freshness_unverified",
    "conflicting_evidence",
    "needs_external_validation",
}
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    # Only whitespace and case: numbers, negations and place names must still differ.
    return _SPACE.sub(" ", text).strip().casefold()


def canonical_filters(filters: dict) -> dict:
    return {
        "region": filters.get("region", "NZ"),
        "source_types": sorted(filters.get("source_types") or []),
    }


def gap_key(question: str, filters: dict, reason_type: str, subquestion: str) -> str:
    identity = [
        normalize(question),
        canonical_filters(filters),
        reason_type,
        normalize(subquestion),
    ]
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class GapService:
    def __init__(self, db: Database):
        self.db = db

    def write(
        self,
        connection: sqlite3.Connection,
        qa_id: str,
        question: str,
        filters: dict,
        draft: AnswerDraft,
    ) -> list[dict]:
        """AnswerService hook: runs inside the QA transaction, so it rolls back with it."""
        written: dict[str, dict] = {}
        for missing in draft.missing_evidence:
            key = gap_key(question, filters, missing.reason_type, missing.subquestion)
            scope = {"filters": canonical_filters(filters), "subquestion": missing.subquestion}
            queries = json.dumps(missing.suggested_queries, ensure_ascii=False)
            stamp = now()
            existing = connection.execute(
                "SELECT id FROM knowledge_gaps WHERE gap_key=? AND status='open'", (key,)
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE knowledge_gaps SET qa_id=?, missing_evidence=?, "
                    "suggested_queries_json=?, updated_at=? WHERE id=?",
                    (qa_id, missing.needed_evidence, queries, stamp, existing["id"]),
                )
                gap_id = existing["id"]
            else:
                gap_id = str(uuid4())
                connection.execute(
                    "INSERT INTO knowledge_gaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        gap_id,
                        qa_id,
                        key,
                        question,
                        json.dumps(scope, ensure_ascii=False),
                        missing.reason_type,
                        missing.needed_evidence,
                        queries,
                        "open",
                        None,
                        stamp,
                        stamp,
                    ),
                )
            written[gap_id] = dict(
                connection.execute("SELECT * FROM knowledge_gaps WHERE id=?", (gap_id,)).fetchone()
            )
        return list(written.values())

    def edit(self, gap_id: str, missing: MissingEvidence) -> dict:
        """User edit of an open gap; the key is recomputed and must stay unique."""
        with self.db.transaction() as c:
            gap = self._open(c, gap_id)
            scope = json.loads(gap["scope_json"])
            key = gap_key(
                gap["question"], scope["filters"], missing.reason_type, missing.subquestion
            )
            clash = c.execute(
                "SELECT id FROM knowledge_gaps WHERE gap_key=? AND status='open' AND id!=?",
                (key, gap_id),
            ).fetchone()
            if clash:
                raise AppError("GAP_DUPLICATE", "An open gap with this question already exists.")
            scope["subquestion"] = missing.subquestion
            c.execute(
                "UPDATE knowledge_gaps SET gap_key=?, scope_json=?, reason_type=?, "
                "missing_evidence=?, suggested_queries_json=?, updated_at=? WHERE id=?",
                (
                    key,
                    json.dumps(scope, ensure_ascii=False),
                    missing.reason_type,
                    missing.needed_evidence,
                    json.dumps(missing.suggested_queries, ensure_ascii=False),
                    now(),
                    gap_id,
                ),
            )
        return self.get(gap_id)

    def resolve(self, gap_id: str, resolution_note: str) -> dict:
        note = resolution_note.strip()
        if not note:
            raise AppError("RESOLUTION_NOTE_REQUIRED", "Explain how the gap was resolved.")
        return self._close(gap_id, "resolved", note)

    def dismiss(self, gap_id: str, note: str | None = None) -> dict:
        return self._close(gap_id, "dismissed", (note or "").strip() or None)

    def reopen(self, gap_id: str) -> dict:
        with self.db.transaction() as c:
            gap = c.execute("SELECT * FROM knowledge_gaps WHERE id=?", (gap_id,)).fetchone()
            if gap is None:
                raise AppError("GAP_NOT_FOUND", "The knowledge gap does not exist.")
            if gap["status"] == "open":
                return dict(gap)
            if c.execute(
                "SELECT 1 FROM knowledge_gaps WHERE gap_key=? AND status='open'", (gap["gap_key"],)
            ).fetchone():
                raise AppError("GAP_DUPLICATE", "A newer open gap already covers this question.")
            c.execute(
                "UPDATE knowledge_gaps SET status='open', resolution_note=NULL, updated_at=? "
                "WHERE id=?",
                (now(), gap_id),
            )
        return self.get(gap_id)

    def get(self, gap_id: str) -> dict:
        with self.db.connect() as c:
            gap = c.execute("SELECT * FROM knowledge_gaps WHERE id=?", (gap_id,)).fetchone()
        if gap is None:
            raise AppError("GAP_NOT_FOUND", "The knowledge gap does not exist.")
        return dict(gap)

    def list_gaps(self, status: str | None = "open") -> list[dict]:
        with self.db.connect() as c:
            if status is None:
                rows = c.execute("SELECT * FROM knowledge_gaps ORDER BY updated_at DESC")
            else:
                rows = c.execute(
                    "SELECT * FROM knowledge_gaps WHERE status=? ORDER BY updated_at DESC",
                    (status,),
                )
            return [dict(r) for r in rows]

    def _close(self, gap_id: str, status: str, note: str | None) -> dict:
        with self.db.transaction() as c:
            self._open(c, gap_id)
            c.execute(
                "UPDATE knowledge_gaps SET status=?, resolution_note=?, updated_at=? WHERE id=?",
                (status, note, now(), gap_id),
            )
        return self.get(gap_id)

    @staticmethod
    def _open(c, gap_id: str):
        gap = c.execute("SELECT * FROM knowledge_gaps WHERE id=?", (gap_id,)).fetchone()
        if gap is None:
            raise AppError("GAP_NOT_FOUND", "The knowledge gap does not exist.")
        if gap["status"] != "open":
            raise AppError("GAP_NOT_OPEN", "Only an open gap can be changed.")
        return gap
