from pathlib import Path

import pytest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import MetadataCorrection, MissingEvidence, RetrievalFilters
from gridlens.errors import AppError
from gridlens.providers.fakes import FakeAnswerProvider
from gridlens.services.gaps import gap_key

GUIDE = "https://synthetic.example/connection-guide"


@pytest.fixture
def app(tmp_path):
    return build_container(Settings(project_root=Path(tmp_path)))


def publish(app, jurisdiction="NZ"):
    source = app.discovery.add_source(GUIDE)
    preview = app.snapshots.capture(source.source_id)
    corrected = app.review.update_metadata(
        preview.version_id,
        preview.snapshot_sha256,
        MetadataCorrection(title="Guide", jurisdiction=jurisdiction, source_type="technical"),
    )
    app.review.approve(preview.version_id, corrected.snapshot_sha256, "Researcher")
    app.ingestion.ingest(preview.version_id, "seed")
    return preview.version_id


keys = iter(range(10_000))


def ask(app, question="How does the synthetic process start?", provider=None, **filters):
    provider = provider or FakeAnswerProvider()
    return app.answer_service.ask(
        question, RetrievalFilters(**filters), f"op-{next(keys)}", provider
    )


def count(app, sql, *args):
    with app.db.connect() as c:
        return c.execute(sql, args).fetchone()[0]


def test_empty_library_creates_one_open_gap_and_repeats_merge(app):
    first = ask(app)
    [gap] = app.gaps.list_gaps()
    assert gap["reason_type"] == "no_evidence" and gap["status"] == "open"
    assert gap["suggested_queries_json"] and '"filters"' in gap["scope_json"]
    assert [g["id"] for g in first.gaps] == [gap["id"]]
    second = ask(app, question="  how   does the SYNTHETIC process start? ")
    [merged] = app.gaps.list_gaps()
    assert merged["id"] == gap["id"] and merged["qa_id"] == second.qa_id
    assert count(app, "SELECT COUNT(*) FROM knowledge_gaps") == 1


@pytest.mark.parametrize(
    "other",
    [
        "Is a 50 MW load allowed?",
        "Is a 5 MW load not allowed?",
        "Is a 5 MW load allowed in Auckland?",
    ],
)
def test_numbers_negation_and_places_are_not_merged(app, other):
    ask(app, question="Is a 5 MW load allowed?")
    ask(app, question=other)
    assert len(app.gaps.list_gaps()) == 2


def test_scope_is_part_of_the_key(app):
    ask(app, region="NZ")
    ask(app, region="US")
    ask(app, region="ALL", source_types=["policy", "paper"])
    ask(app, region="ALL", source_types=["paper", "policy"])  # same set, different order
    assert len(app.gaps.list_gaps()) == 3
    assert gap_key("Q", {"region": "NZ"}, "no_evidence", "s") == gap_key(
        " q ", {"region": "NZ", "source_types": []}, "no_evidence", "S"
    )


def test_jurisdiction_mismatch_and_verified_partial_drafts(app):
    publish(app, jurisdiction="US")
    ask(app, region="NZ")
    assert [g["reason_type"] for g in app.gaps.list_gaps()] == ["jurisdiction_mismatch"]
    partial = ask(app, region="US")
    assert partial.evidence_status == "partial"
    reasons = sorted(g["reason_type"] for g in app.gaps.list_gaps())
    assert reasons == ["jurisdiction_mismatch", "needs_external_validation"]


def test_service_failures_and_stale_context_create_no_gaps(app):
    publish(app)
    failed = ask(app, provider=FakeAnswerProvider("USAGE_LIMITED"))
    assert failed.execution_status == "failed" and failed.gaps == []
    invalid = ask(app, provider=FakeAnswerProvider("CITATION_INVALID"))
    assert invalid.execution_status == "failed"
    assert count(app, "SELECT COUNT(*) FROM knowledge_gaps") == 0


def test_resolution_needs_a_note_and_a_later_gap_opens_a_new_record(app):
    ask(app)
    [gap] = app.gaps.list_gaps()
    with pytest.raises(AppError) as raised:
        app.gaps.resolve(gap["id"], "  ")
    assert raised.value.code == "RESOLUTION_NOTE_REQUIRED"
    resolved = app.gaps.resolve(gap["id"], "Found the official guide and approved it.")
    assert resolved["status"] == "resolved" and resolved["resolution_note"]
    ask(app)  # evidence still missing later: a new open record, history kept
    assert len(app.gaps.list_gaps()) == 1 and app.gaps.list_gaps()[0]["id"] != gap["id"]
    assert count(app, "SELECT COUNT(*) FROM knowledge_gaps") == 2
    with pytest.raises(AppError) as raised:
        app.gaps.reopen(gap["id"])
    assert raised.value.code == "GAP_DUPLICATE"
    with pytest.raises(AppError) as raised:
        app.gaps.resolve(gap["id"], "again")
    assert raised.value.code == "GAP_NOT_OPEN"


def test_false_positive_can_be_dismissed_and_reopened(app):
    ask(app)
    [gap] = app.gaps.list_gaps()
    assert app.gaps.dismiss(gap["id"], "Out of scope for this study")["status"] == "dismissed"
    assert app.gaps.list_gaps() == []
    assert app.gaps.reopen(gap["id"])["status"] == "open"


def test_edits_recompute_the_key_and_keep_open_gaps_unique(app):
    ask(app, question="First question?")
    ask(app, question="Second question?")
    first, second = sorted(app.gaps.list_gaps(), key=lambda g: g["question"])
    edited = app.gaps.edit(
        first["id"],
        MissingEvidence(
            reason_type="partial_coverage",
            subquestion="Which stage?",
            needed_evidence="A stage list.",
            suggested_queries=["NZ stages"],
        ),
    )
    assert edited["gap_key"] != first["gap_key"] and edited["reason_type"] == "partial_coverage"
    assert '"Which stage?"' in edited["scope_json"]
    # Turning the second gap into the same question as the first is refused.
    with app.db.transaction() as c:
        c.execute(
            "UPDATE knowledge_gaps SET question=? WHERE id=?", (first["question"], second["id"])
        )
    with pytest.raises(AppError) as raised:
        app.gaps.edit(
            second["id"],
            MissingEvidence(
                reason_type="partial_coverage",
                subquestion="which  STAGE?",
                needed_evidence="x",
                suggested_queries=["y"],
            ),
        )
    assert raised.value.code == "GAP_DUPLICATE"


def test_gap_write_failure_rolls_back_the_answer(app):
    with app.db.transaction() as c:
        c.execute(
            "CREATE TRIGGER no_gaps BEFORE INSERT ON knowledge_gaps "
            "BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
        )
    with pytest.raises(AppError) as raised:
        ask(app)
    assert raised.value.code == "QA_SAVE_FAILED"
    assert count(app, "SELECT COUNT(*) FROM qa_records") == 0
