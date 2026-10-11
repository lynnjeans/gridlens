"""Server-side citation checks. They prove provenance, not semantic entailment."""

import re

from gridlens.contracts import AnswerDraft, RetrievalContext

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
