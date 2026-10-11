import json
import re
from pathlib import Path

import pytest

from gridlens.bootstrap import build_container
from gridlens.config import PROJECT_ROOT, Settings
from gridlens.evaluation import load_cases, review_template, run_cases, score

QUESTIONS = PROJECT_ROOT / "evals/questions.json"
GOLD = PROJECT_ROOT / "evals/gold.json"
SUPPORTED = [f"R{n:02d}" for n in range(1, 9)]
INSUFFICIENT = [f"R{n:02d}" for n in range(9, 13)]
CITATION = {
    "number": 1,
    "chunk_id": "c",
    "quote": "q",
    "claim_ids": ["c1"],
    "locator": {"kind": "html", "paragraph_index": 1},
    "source": {"version_id": "v", "snapshot_sha256": "s" * 64},
}


def report(*, live=True, citations=1, context="Reference passage here."):
    results = [
        {
            "id": i,
            "split": "formal_supported" if i in SUPPORTED else "formal_insufficient",
            "question": i,
            "qa_id": i,
            "execution_status": "completed",
            "evidence_status": "answered",
            "error": None,
            "claims": [],
            "citations": [CITATION] * citations,
            "context_texts": [context],
            "model_id": "model-x",
            "output_mode": "schema",
        }
        for i in SUPPORTED + INSUFFICIENT
    ]
    return {
        "run_id": "r",
        "mode": "live" if live else "fixture",
        "acceptance_eligible": live,
        "warning": None if live else "FIXTURE",
        "corpus": {},
        "prompt_version": "answer_v1",
        "results": results,
    }


def gold(passage="Reference  passage", missing=()):  # verbatim, whitespace-normalized
    return {
        "cases": [
            {"id": i, "reference_passages": [] if i in missing else [passage]} for i in SUPPORTED
        ]
    }


def reviews(twos=8, handled=4, substantive=10, cited=10, supported=10, drop=()):
    cases = []
    for n, i in enumerate(SUPPORTED):
        cases.append(
            {
                "id": i,
                "reviewer": "Teammate",
                "answer_score": 2 if n < twos else 1,
                "substantive_claims": substantive,
                "cited_claims": cited,
                "supported_cited_claims": supported,
            }
        )
    for n, i in enumerate(INSUFFICIENT):
        cases.append(
            {
                "id": i,
                "reviewer": "Teammate",
                "insufficiency_handled": n < handled,
                "substantive_claims": 0,
                "cited_claims": 0,
                "supported_cited_claims": 0,
            }
        )
    return {"cases": [c for c in cases if c["id"] not in drop]}


def metric(result, name):
    return next(m for m in result["metrics"] if m["name"] == name)


def test_question_bank_is_verbatim_and_gold_is_empty():
    cases = load_cases(QUESTIONS)
    prd = (PROJECT_ROOT / "docs/00_PRD.md").read_text()
    for case in cases:
        assert f"| {case.id} | {case.question} | {case.expected_behavior} |" in prd
    assert [c.split for c in cases].count("formal_supported") == 8
    assert [c.split for c in cases].count("formal_insufficient") == 4
    assert [c.split for c in cases].count("discussion") == 3
    template = json.loads(GOLD.read_text())
    assert all(
        not c["reference_passages"]
        and not c["acceptable_points"]
        and c["status"] == "awaiting_human"
        for c in template["cases"]
    )


def test_complete_live_scores_can_pass():
    result = score(report(), gold(), reviews())
    assert result["overall"] == "pass"
    assert {m["status"] for m in result["metrics"]} == {"pass"}
    assert result["reviewers"] == ["Teammate"]


@pytest.mark.parametrize(
    "kwargs,name,expected",
    [
        ({"twos": 7}, "answer_quality", "pass"),
        ({"twos": 6}, "answer_quality", "fail"),
        ({"handled": 3}, "insufficient_evidence_handling", "fail"),
        ({"cited": 9, "supported": 9}, "citation_coverage", "fail"),
        ({"supported": 9}, "citation_support", "pass"),
        ({"supported": 8}, "citation_support", "fail"),
    ],
)
def test_thresholds(kwargs, name, expected):
    result = score(report(), gold(), reviews(**kwargs))
    assert metric(result, name)["status"] == expected
    if expected == "fail":
        assert result["overall"] == "fail"


def test_retrieval_hit_threshold_and_missing_gold():
    seven = score(report(context="unrelated"), gold(), reviews())
    assert metric(seven, "retrieval_hit")["status"] == "fail"
    missing = score(report(), gold(missing=("R03",)), reviews())
    assert metric(missing, "retrieval_hit")["status"] == "awaiting_input"
    assert missing["overall"] == "awaiting_input"


def test_missing_reviews_never_pass():
    for reviews_value in (None, reviews(drop=("R05",)), reviews(drop=("R10",))):
        result = score(report(), gold(), reviews_value)
        assert result["overall"] == "awaiting_input"
    invalid = reviews()
    invalid["cases"][0]["answer_score"] = 3
    assert metric(score(report(), gold(), invalid), "answer_quality")["status"] == "awaiting_input"


def test_zero_denominators_are_not_passes():
    result = score(report(citations=0), gold(), reviews(substantive=0, cited=0, supported=0))
    assert metric(result, "citation_traceability")["status"] == "awaiting_input"
    assert metric(result, "citation_coverage")["status"] == "awaiting_input"
    assert metric(result, "citation_support")["status"] == "awaiting_input"
    assert result["overall"] == "awaiting_input"


def test_traceability_is_automatic_and_distinct_from_support():
    broken = report()
    broken["results"][0]["citations"] = [{**CITATION, "quote": ""}]
    result = score(broken, gold(), reviews())
    trace = metric(result, "citation_traceability")
    support = metric(result, "citation_support")
    assert trace["method"] == "automatic" and trace["status"] == "fail"
    assert support["method"] == "human" and support["status"] == "pass"
    assert "not proof" in trace["detail"]


def test_fixture_runs_are_never_acceptance():
    result = score(report(live=False), gold(), reviews())
    assert result["overall"] == "fixture_only_not_acceptance"


def test_fixture_evaluate_runs_formal_cases_only(tmp_path):
    app = build_container(Settings(project_root=Path(tmp_path)))
    cases = load_cases(QUESTIONS)
    first = run_cases(app, cases, app.answers, run_id="t1")
    assert [r["id"] for r in first["results"]] == SUPPORTED + INSUFFICIENT
    assert first["acceptance_eligible"] is False and "not valid" in first["warning"]
    assert first["corpus"]["eligible_versions"] == 0
    assert first["retrieval"]["top_k"] == 10
    # Same run ID replays saved answers instead of asking again.
    again = run_cases(app, cases, app.answers, run_id="t1")
    assert [r["qa_id"] for r in again["results"]] == [r["qa_id"] for r in first["results"]]
    template = review_template(first)
    assert all(
        v is None
        for c in template["cases"]
        for k, v in c.items()
        if k not in {"id", "reviewer", "notes"}
    )
    assert re.fullmatch(r"R\d\d", template["cases"][0]["id"])
