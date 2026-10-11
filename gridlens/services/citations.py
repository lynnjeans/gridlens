"""Server-side citation checks. They prove provenance, not semantic entailment."""

import re

from gridlens.contracts import AnswerDraft, RetrievalContext
from gridlens.db import Database

_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def citation_problems(draft: AnswerDraft, context: RetrievalContext) -> list[str]:
    """Reasons a draft cannot be published; empty when every quote is traceable."""
    chunks = {chunk.chunk_id: chunk for chunk in context.chunks}
    eligible = set(context.eligible_version_ids)
    problems = []
    for claim in draft.claims:
        for evidence in claim.evidence:
            chunk = chunks.get(evidence.chunk_id)
            if chunk is None:
                problems.append(
                    f"claim {claim.claim_id}: chunk {evidence.chunk_id} is not in the evidence"
                )
                continue
            if chunk.version_id not in eligible:
                problems.append(
                    f"claim {claim.claim_id}: chunk {evidence.chunk_id} is no longer eligible"
                )
                continue
            quote = normalize(evidence.support_quote)
            if not quote or quote not in normalize(chunk.text):
                problems.append(
                    f"claim {claim.claim_id}: quote is not verbatim text of {evidence.chunk_id}"
                )
    return problems


def source_statuses(db: Database, version_ids: list[str], fingerprint: str | None) -> dict:
    """Current status of cited versions, computed on every read of a historical answer."""
    if not version_ids:
        return {}
    placeholders = ",".join("?" for _ in version_ids)
    with db.connect() as c:
        rows = c.execute(
            f"SELECT * FROM document_versions WHERE id IN ({placeholders})", tuple(version_ids)
        ).fetchall()
    statuses = {}
    for row in rows:
        if row["review_status"] == "revoked":
            status = "revoked"
        elif row["version_status"] == "superseded":
            status = "superseded"
        elif (
            row["review_status"] == "approved"
            and row["ingestion_status"] == "ready"
            and row["version_status"] == "active"
            and row["approved_snapshot_sha256"] == row["snapshot_sha256"]
            and (fingerprint is None or row["index_fingerprint"] == fingerprint)
        ):
            status = "current"
        else:
            status = "not_current"
        statuses[row["id"]] = status
    return statuses
