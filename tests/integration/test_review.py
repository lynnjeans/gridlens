import hashlib
import sqlite3

import pytest

from gridlens.contracts import FetchedDocument, SearchHitDTO
from gridlens.documents.snapshots import SnapshotService
from gridlens.errors import AppError
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository
from gridlens.services.review import ReviewService


class Fetcher:
    def __init__(self, body):
        self.body = body

    def fetch(self, url):
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            content_type="text/html",
            body=self.body,
            raw_sha256=hashlib.sha256(self.body).hexdigest(),
            fetched_at="2026-10-11T00:00:00+00:00",
            redirect_count=0,
        )


def prepared(db, tmp_path):
    sources = SourceRepository(db)
    source_id = sources.save_candidate(
        SearchHitDTO(
            title="Reviewable guide",
            url="https://example.org/guide",
            snippet="candidate",
            provider_rank=1,
            source_type="technical",
            jurisdiction="NZ",
        ),
        "https://example.org/guide",
    )
    root = tmp_path / "data/fixture"
    preview = SnapshotService(
        db,
        sources,
        Fetcher(b"<main><h1>Guide</h1><p>Reviewable grid evidence.</p></main>"),
        root,
        max_pdf_pages=10,
        pdf_timeout_seconds=5,
    ).capture(source_id)
    return ReviewService(db, sources, root), preview, sources


def event_count(db):
    with db.connect() as connection:
        return connection.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]


def test_approve_binds_hash_and_duplicate_is_idempotent(db, tmp_path):
    review, preview, _ = prepared(db, tmp_path)
    approved = review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    assert approved.review_status == "approved"
    assert approved.approved_snapshot_sha256 == preview.snapshot_sha256
    assert approved.changed
    repeated = review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    assert not repeated.changed
    assert event_count(db) == 1


def test_stale_hash_and_corrupt_original_cannot_be_approved(db, tmp_path):
    review, preview, sources = prepared(db, tmp_path)
    with pytest.raises(AppError) as raised:
        review.approve(preview.version_id, "0" * 64, "Researcher")
    assert raised.value.code == "REVIEW_STALE"

    row = sources.get_version(preview.version_id)
    (tmp_path / "data/fixture" / row["raw_path"]).write_bytes(b"changed")
    with pytest.raises(AppError) as raised:
        review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    assert raised.value.code == "SNAPSHOT_INTEGRITY_FAILED"
    assert sources.get_version(preview.version_id)["review_status"] == "pending"
    assert event_count(db) == 0


def test_reject_requires_reason_and_reopen_resets_state(db, tmp_path):
    review, preview, sources = prepared(db, tmp_path)
    with pytest.raises(AppError) as raised:
        review.reject(preview.version_id, "Researcher", " ")
    assert raised.value.code == "REJECT_REASON_REQUIRED"

    rejected = review.reject(preview.version_id, "Researcher", "Wrong jurisdiction")
    assert rejected.review_status == "rejected"
    assert not review.reject(preview.version_id, "Researcher", "Wrong jurisdiction").changed
    reopened = review.reopen(preview.version_id, "Researcher", "Corrected metadata")
    assert reopened.review_status == "pending"
    assert reopened.ingestion_status == "not_started"
    assert reopened.version_status == "candidate"
    assert reopened.approved_snapshot_sha256 is None
    assert not review.reopen(preview.version_id, "Researcher").changed
    assert event_count(db) == 2
    assert sources.get_version(preview.version_id)["index_fingerprint"] is None


def test_revoke_immediately_removes_retrieval_eligibility_and_reopen_resets(db, tmp_path):
    review, preview, sources = prepared(db, tmp_path)
    review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    with db.transaction() as connection:
        connection.execute(
            "UPDATE document_versions SET ingestion_status='ready', version_status='active', "
            "index_fingerprint='fixture' WHERE id=?",
            (preview.version_id,),
        )
    assert len(ResearchRepository(db).eligible_versions("fixture")) == 1
    revoked = review.revoke(preview.version_id, "Researcher", "Source withdrawn")
    assert revoked.review_status == "revoked"
    assert ResearchRepository(db).eligible_versions("fixture") == []
    assert not review.revoke(preview.version_id, "Researcher").changed
    reopened = review.reopen(preview.version_id, "Researcher")
    assert reopened.version_status == "candidate"
    assert reopened.ingestion_status == "not_started"
    assert sources.get_version(preview.version_id)["approved_snapshot_sha256"] is None


def test_invalid_transition_and_reviewer_are_rejected(db, tmp_path):
    review, preview, _ = prepared(db, tmp_path)
    with pytest.raises(AppError) as raised:
        review.reopen(preview.version_id, "Researcher")
    assert raised.value.code == "REVIEW_STATE_INVALID"
    with pytest.raises(AppError) as raised:
        review.approve(preview.version_id, preview.snapshot_sha256, " ")
    assert raised.value.code == "REVIEWER_REQUIRED"
    review.reject(preview.version_id, "Researcher", "Not applicable")
    with pytest.raises(AppError) as raised:
        review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    assert raised.value.code == "REVIEW_STATE_INVALID"


def test_event_failure_rolls_back_state_change(db, tmp_path):
    review, preview, sources = prepared(db, tmp_path)
    with db.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER fail_review_event BEFORE INSERT ON review_events "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    row = sources.get_version(preview.version_id)
    assert row["review_status"] == "pending"
    assert row["approved_snapshot_sha256"] is None
    assert event_count(db) == 0
