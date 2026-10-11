"""One synthetic path through every user-facing stage (PRD AC-01…AC-08)."""

from pathlib import Path

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import DiscoveryRequest, MetadataCorrection, RetrievalFilters
from gridlens.services.export import ExportSelection


def test_search_review_index_ask_gap_export_restart(tmp_path):
    app = build_container(Settings(project_root=Path(tmp_path)))

    # Discover: fixture search returns a candidate; nothing is fetched yet.
    run = app.discovery.discover(DiscoveryRequest(topic="NZ large-load connection"), "op-search")
    [candidate] = run.candidates
    assert app.research.list_versions() == []

    # Review: capture, correct reviewed metadata, approve the exact preview the user saw.
    preview = app.snapshots.capture(candidate.source_id)
    corrected = app.review.update_metadata(
        preview.version_id,
        preview.snapshot_sha256,
        MetadataCorrection(
            title=candidate.title,
            publisher="Synthetic publisher",
            jurisdiction="NZ",
            source_type="technical",
        ),
    )
    app.review.approve(preview.version_id, corrected.snapshot_sha256, "Researcher")

    # Index: the version becomes Ready/Active only after a verified index.
    indexed = app.ingestion.ingest(preview.version_id, "op-index")
    assert indexed.status == "completed" and indexed.indexed_chunks > 0
    eligible = app.research.eligible_versions(app.ingestion.fingerprint, None)
    assert [v["id"] for v in eligible] == [preview.version_id]

    # Ask: evidence comes only from the approved version; citations come from snapshots.
    answer = app.answer_service.ask(
        "How does the synthetic process start?", RetrievalFilters(), "op-ask", app.answers
    )
    assert answer.execution_status == "completed"
    assert {c["source"]["version_id"] for c in answer.citations} == {preview.version_id}
    assert answer.citations[0]["source"]["title"] == candidate.title

    # Gaps: the partial answer recorded an open, actionable gap.
    [gap] = app.gaps.list_gaps()
    assert gap["qa_id"] == answer.qa_id and gap["suggested_queries_json"] != "[]"

    # Export: the log carries the source, the answer and the gap.
    log = app.export.export(
        ExportSelection(version_ids=[preview.version_id], qa_ids=[answer.qa_id])
    )
    assert "## Current approved sources" in log and "## Knowledge gaps" in log
    assert answer.citations[0]["quote"].rstrip(".")[:30] in log.replace("\\", "")

    # Restart: a fresh process sees the same state and answer; recovery finds nothing to fix.
    restarted = build_container(Settings(project_root=Path(tmp_path)))
    report = restarted.recovery.recover()
    assert report.interrupted_ingestions == [] and report.interrupted_searches == []
    assert restarted.answer_service.replay("op-ask") == answer
    assert [g["id"] for g in restarted.gaps.list_gaps()] == [gap["id"]]
