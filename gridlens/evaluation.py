"""Evaluation runs and PRD §15.3 scoring that never manufactures a pass.

A run records what the system did on the frozen formal cases (R01–R12). Scoring needs
human-written gold passages and human review scores; anything missing yields
`awaiting_input`. Automatic citation locatability is reported separately from the
human-judged semantic support rate. Fixture runs can never count as acceptance.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from gridlens.contracts import DTO, AnswerProvider, RetrievalFilters
from gridlens.providers.chatgpt_oauth import PROMPT_VERSION
from gridlens.services.citations import normalize

FORMAL_SUPPORTED = [f"R{n:02d}" for n in range(1, 9)]
FORMAL_INSUFFICIENT = [f"R{n:02d}" for n in range(9, 13)]
Status = Literal["pass", "fail", "awaiting_input"]


class Case(DTO):
    id: str
    question: str
    expected_behavior: str
    split: Literal["formal_supported", "formal_insufficient", "discussion"]
    filters: dict = Field(default_factory=dict)


class Metric(DTO):
    name: str
    numerator: int | None
    denominator: int | None
    target: str
    status: Status
    method: Literal["automatic", "human"]
    detail: str = ""


def load_cases(path: Path) -> list[Case]:
    data = json.loads(path.read_text("utf-8"))
    cases = [Case.model_validate(item) for item in data["cases"]]
    ids = [c.id for c in cases]
    if ids != [f"R{n:02d}" for n in range(1, 16)]:
        raise ValueError("The question bank must contain R01–R15 in order")
    return cases


def corpus_fingerprint(db, index_fingerprint: str | None) -> dict:
    """Identifies the frozen corpus: eligible versions and their approved snapshots."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, snapshot_sha256 FROM document_versions WHERE review_status='approved' "
            "AND ingestion_status='ready' AND version_status='active' "
            "AND approved_snapshot_sha256=snapshot_sha256 AND index_fingerprint IS ?",
            (index_fingerprint,),
        ).fetchall()
    pairs = sorted((r[0], r[1]) for r in rows)
    digest = hashlib.sha256(json.dumps(pairs).encode()).hexdigest()
    return {
        "eligible_versions": len(pairs),
        "sha256": digest,
        "index_fingerprint": index_fingerprint,
    }


def run_cases(container, cases: list[Case], provider: AnswerProvider | None, *, run_id: str):
    """Asks the formal cases once each; operation keys make reruns replay, not re-call."""
    settings = container.settings
    results = []
    for case in cases:
        if case.split == "discussion":
            continue
        envelope = container.answer_service.ask(
            case.question, RetrievalFilters(**case.filters), f"eval-{run_id}-{case.id}", provider
        )
        with container.db.connect() as c:
            record = dict(
                c.execute("SELECT * FROM qa_records WHERE id=?", (envelope.qa_id,)).fetchone()
            )
            context_texts = [
                r[0]
                for r in c.execute(
                    "SELECT text FROM chunks WHERE id IN (SELECT value FROM json_each(?))",
                    (record["context_chunk_ids_json"],),
                )
            ]
        results.append(
            {
                "id": case.id,
                "split": case.split,
                "question": case.question,
                "qa_id": envelope.qa_id,
                "execution_status": envelope.execution_status,
                "evidence_status": envelope.evidence_status,
                "error": envelope.error,
                "claims": [c.model_dump() for c in envelope.claims],
                "citations": envelope.citations,
                "context_texts": context_texts,
                "model_id": record["model_id"],
                "output_mode": record["output_mode"],
            }
        )
    return {
        "run_id": run_id,
        "mode": settings.mode,
        "acceptance_eligible": settings.mode == "live",
        "warning": None
        if settings.mode == "live"
        else "FIXTURE RUN: synthetic data and answers; not valid for acceptance.",
        "created_at": datetime.now(UTC).isoformat(),
        "corpus": corpus_fingerprint(
            container.db, container.ingestion.fingerprint if container.ingestion else None
        ),
        "prompt_version": PROMPT_VERSION,
        "retrieval": {
            "top_k": settings.retrieval_top_k,
            "context_k": settings.context_top_k,
            "max_context_tokens": settings.max_context_tokens,
            "chunk_tokens": settings.chunk_tokens,
            "chunk_overlap": settings.chunk_overlap,
        },
        "results": results,
    }


def review_template(report: dict) -> dict:
    """Blank human review sheet; every score starts empty (never pre-filled)."""
    cases = []
    for result in report["results"]:
        entry = {"id": result["id"], "reviewer": "", "notes": ""}
        if result["split"] == "formal_supported":
            entry |= {
                "answer_score": None,
                "substantive_claims": None,
                "cited_claims": None,
                "supported_cited_claims": None,
            }
        else:
            entry |= {
                "insufficiency_handled": None,
                "substantive_claims": None,
                "cited_claims": None,
                "supported_cited_claims": None,
            }
        cases.append(entry)
    return {"run_id": report["run_id"], "cases": cases}


def _status(numerator, denominator, passed: bool | None) -> Status:
    if numerator is None or denominator in (None, 0) or passed is None:
        return "awaiting_input"
    return "pass" if passed else "fail"


def score(report: dict, gold: dict, reviews: dict | None) -> dict:
    results = {r["id"]: r for r in report["results"]}
    gold_cases = {g["id"]: g for g in gold.get("cases", [])}
    review_cases = {r["id"]: r for r in (reviews or {}).get("cases", [])}
    metrics: list[Metric] = []

    # Retrieval hit (R01–R08): a human-marked reference passage appears in the final context.
    hits, known = 0, 0
    for case_id in FORMAL_SUPPORTED:
        passages = [p for p in gold_cases.get(case_id, {}).get("reference_passages", []) if p]
        result = results.get(case_id)
        if not passages or result is None:
            continue
        known += 1
        context = [normalize(text) for text in result["context_texts"]]
        if any(normalize(p) in text for p in passages for text in context):
            hits += 1
    complete = known == len(FORMAL_SUPPORTED)
    metrics.append(
        Metric(
            name="retrieval_hit",
            numerator=hits if complete else None,
            denominator=len(FORMAL_SUPPORTED),
            target=">= 7/8",
            method="automatic",
            status=_status(
                hits if complete else None, len(FORMAL_SUPPORTED), hits >= 7 if complete else None
            ),
            detail=f"gold reference passages present for {known}/8 cases",
        )
    )

    # Answer quality (R01–R08): human 0/1/2 scores; target at least seven 2s.
    scores = [review_cases.get(i, {}).get("answer_score") for i in FORMAL_SUPPORTED]
    valid = all(s in (0, 1, 2) for s in scores)
    twos = sum(1 for s in scores if s == 2)
    metrics.append(
        Metric(
            name="answer_quality",
            numerator=twos if valid else None,
            denominator=8,
            target=">= 7/8 scored 2",
            method="human",
            status=_status(twos if valid else None, 8, twos >= 7 if valid else None),
        )
    )

    # Insufficient-evidence handling (R09–R12): human pass/fail, 4/4.
    handled = [review_cases.get(i, {}).get("insufficiency_handled") for i in FORMAL_INSUFFICIENT]
    valid = all(isinstance(h, bool) for h in handled)
    passed = sum(1 for h in handled if h is True)
    metrics.append(
        Metric(
            name="insufficient_evidence_handling",
            numerator=passed if valid else None,
            denominator=4,
            target="4/4",
            method="human",
            status=_status(passed if valid else None, 4, passed == 4 if valid else None),
        )
    )

    # Citation coverage and semantic support: human claim counts across formal answers.
    formal = FORMAL_SUPPORTED + FORMAL_INSUFFICIENT
    rows = [review_cases.get(i, {}) for i in formal]
    counts_ok = all(
        all(
            isinstance(r.get(k), int) and r.get(k) >= 0
            for k in ("substantive_claims", "cited_claims", "supported_cited_claims")
        )
        for r in rows
    )
    substantive = sum(r.get("substantive_claims") or 0 for r in rows) if counts_ok else None
    cited = sum(r.get("cited_claims") or 0 for r in rows) if counts_ok else None
    supported = sum(r.get("supported_cited_claims") or 0 for r in rows) if counts_ok else None
    metrics.append(
        Metric(
            name="citation_coverage",
            numerator=cited,
            denominator=substantive,
            target="100%",
            method="human",
            status=_status(cited, substantive, cited == substantive if counts_ok else None),
        )
    )
    metrics.append(
        Metric(
            name="citation_support",
            numerator=supported,
            denominator=cited,
            target=">= 90%",
            method="human",
            status=_status(
                supported, cited, supported * 10 >= cited * 9 if counts_ok and cited else None
            ),
            detail="Semantic support judged by a person; not the automatic locatability below.",
        )
    )

    # Automatic traceability: each citation has version, snapshot, quote and location.
    citations = [c for r in report["results"] for c in r["citations"]]
    traceable = sum(
        1
        for c in citations
        if c.get("quote")
        and c.get("locator")
        and c.get("source", {}).get("version_id")
        and c.get("source", {}).get("snapshot_sha256")
    )
    metrics.append(
        Metric(
            name="citation_traceability",
            numerator=traceable,
            denominator=len(citations),
            target="100%",
            method="automatic",
            status=_status(traceable, len(citations), traceable == len(citations)),
            detail="Automatic locatability only; not proof that the source supports the claim.",
        )
    )

    failures = [
        {"id": r["id"], "execution_status": r["execution_status"], "error": r["error"]}
        for r in report["results"]
        if r["execution_status"] != "completed"
    ]
    statuses = {m.status for m in metrics}
    if not report.get("acceptance_eligible"):
        overall = "fixture_only_not_acceptance"
    elif "awaiting_input" in statuses:
        overall = "awaiting_input"
    else:
        overall = "pass" if statuses == {"pass"} else "fail"
    reviewers = sorted({r.get("reviewer") for r in review_cases.values() if r.get("reviewer")})
    return {
        "run_id": report["run_id"],
        "mode": report["mode"],
        "overall": overall,
        "warning": report.get("warning"),
        "reviewers": reviewers,
        "self_review_disclosure": "Record whether scores were self-assessed (PRD §15.3).",
        "corpus": report["corpus"],
        "prompt_version": report["prompt_version"],
        "models": sorted({r["model_id"] for r in report["results"] if r["model_id"]}),
        "metrics": [m.model_dump() for m in metrics],
        "failures": failures,
        "sample_size": {"formal_cases": len(report["results"])},
    }
