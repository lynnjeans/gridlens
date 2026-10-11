"""Transactional human review state machine for immutable snapshots."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from gridlens.contracts import ParsedSegment, ReviewResult
from gridlens.db import Database, now
from gridlens.documents.snapshots import snapshot_digest
from gridlens.errors import AppError
from gridlens.repositories.sources import SourceRepository


class ReviewService:
    def __init__(self, db: Database, sources: SourceRepository, snapshot_root: Path):
        self.db = db
        self.sources = sources
        self.snapshot_root = snapshot_root.resolve()

    def approve(self, version_id: str, expected_hash: str, reviewer: str) -> ReviewResult:
        reviewer = self._reviewer(reviewer)
        row = self._version(version_id)
        if row["review_status"] == "approved":
            if row["approved_snapshot_sha256"] != expected_hash:
                raise AppError("REVIEW_STALE", "The document preview has changed.")
            self._validate_snapshot(row)
            return self._result(row, changed=False)
        if row["review_status"] != "pending":
            raise AppError("REVIEW_STATE_INVALID", "This version cannot be approved.")
        if row["snapshot_sha256"] != expected_hash:
            raise AppError("REVIEW_STALE", "The document preview has changed.")
        self._validate_snapshot(row)
        return self._transition(
            version_id,
            from_status="pending",
            action="approve",
            reviewer=reviewer,
            reason=None,
            updates={
                "review_status": "approved",
                "approved_snapshot_sha256": row["snapshot_sha256"],
            },
        )

    def reject(self, version_id: str, reviewer: str, reason: str) -> ReviewResult:
        reviewer = self._reviewer(reviewer)
        reason = reason.strip()
        if not reason:
            raise AppError("REJECT_REASON_REQUIRED", "A rejection reason is required.")
        row = self._version(version_id)
        if row["review_status"] == "rejected":
            with self.db.connect() as connection:
                event = connection.execute(
                    "SELECT reason FROM review_events WHERE version_id=? AND action='reject' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (version_id,),
                ).fetchone()
            if event and event["reason"] == reason:
                return self._result(row, changed=False)
            raise AppError("REVIEW_STATE_INVALID", "This version is already rejected.")
        if row["review_status"] != "pending":
            raise AppError("REVIEW_STATE_INVALID", "This version cannot be rejected.")
        return self._transition(
            version_id,
            from_status="pending",
            action="reject",
            reviewer=reviewer,
            reason=reason,
            updates={"review_status": "rejected", "approved_snapshot_sha256": None},
        )

    def revoke(self, version_id: str, reviewer: str, reason: str | None = None) -> ReviewResult:
        reviewer = self._reviewer(reviewer)
        row = self._version(version_id)
        if row["review_status"] == "revoked":
            return self._result(row, changed=False)
        if row["review_status"] != "approved":
            raise AppError("REVIEW_STATE_INVALID", "Only an approved version can be revoked.")
        return self._transition(
            version_id,
            from_status="approved",
            action="revoke",
            reviewer=reviewer,
            reason=reason.strip() if reason else None,
            updates={"review_status": "revoked"},
        )

    def reopen(self, version_id: str, reviewer: str, reason: str | None = None) -> ReviewResult:
        reviewer = self._reviewer(reviewer)
        row = self._version(version_id)
        if row["review_status"] == "pending":
            if self._latest_action(version_id) == "reopen":
                return self._result(row, changed=False)
            raise AppError("REVIEW_STATE_INVALID", "This version is already pending review.")
        if (
            row["review_status"] not in {"rejected", "revoked"}
            or row["version_status"] == "superseded"
        ):
            raise AppError("REVIEW_STATE_INVALID", "This version cannot be reopened.")
        return self._transition(
            version_id,
            from_status=row["review_status"],
            action="reopen",
            reviewer=reviewer,
            reason=reason.strip() if reason else None,
            updates={
                "review_status": "pending",
                "approved_snapshot_sha256": None,
                "ingestion_status": "not_started",
                "version_status": "candidate",
                "index_fingerprint": None,
            },
        )

    def _transition(self, version_id, *, from_status, action, reviewer, reason, updates):
        assignments = ", ".join(f"{field}=?" for field in updates)
        with self.db.transaction() as connection:
            current = connection.execute(
                "SELECT * FROM document_versions WHERE id=?", (version_id,)
            ).fetchone()
            if not current or current["review_status"] != from_status:
                raise AppError("REVIEW_STATE_CHANGED", "The review state changed; reload it.")
            connection.execute(
                f"UPDATE document_versions SET {assignments} WHERE id=?",
                (*updates.values(), version_id),
            )
            connection.execute(
                "INSERT INTO review_events VALUES (?,?,?,?,?,?)",
                (str(uuid4()), version_id, action, reviewer, reason, now()),
            )
        return self._result(self._version(version_id), changed=True)

    def _validate_snapshot(self, row) -> None:
        try:
            raw = self._path(row["raw_path"]).read_bytes()
            segment_data = json.loads(self._path(row["segments_path"]).read_text(encoding="utf-8"))
            segments = [ParsedSegment.model_validate(item) for item in segment_data]
            metadata = json.loads(row["metadata_json"])
        except (OSError, ValueError):
            raise AppError("SNAPSHOT_READ_FAILED", "The saved snapshot is unreadable.") from None
        if not raw or hashlib.sha256(raw).hexdigest() != row["raw_sha256"]:
            raise AppError(
                "SNAPSHOT_INTEGRITY_FAILED", "The saved original does not match its hash."
            )
        if not segments or any(not segment.text.strip() for segment in segments):
            raise AppError("SNAPSHOT_EMPTY", "The snapshot has no reviewable text.")
        parser_version = metadata.get("parser_version")
        if (
            not parser_version
            or snapshot_digest(segments, metadata, parser_version) != row["snapshot_sha256"]
        ):
            raise AppError(
                "SNAPSHOT_INTEGRITY_FAILED", "The saved preview does not match its hash."
            )

    def _path(self, relative: str) -> Path:
        path = (self.snapshot_root / relative).resolve()
        if not path.is_relative_to(self.snapshot_root):
            raise AppError("SNAPSHOT_PATH_INVALID", "The snapshot path is invalid.")
        return path

    def _version(self, version_id: str) -> dict:
        row = self.sources.get_version(version_id)
        if row is None:
            raise AppError("VERSION_NOT_FOUND", "The document version does not exist.")
        return row

    def _latest_action(self, version_id: str) -> str | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT action FROM review_events WHERE version_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (version_id,),
            ).fetchone()
            return row["action"] if row else None

    @staticmethod
    def _reviewer(value: str) -> str:
        value = value.strip()
        if not value:
            raise AppError("REVIEWER_REQUIRED", "A reviewer name is required.")
        return value

    @staticmethod
    def _result(row, *, changed: bool) -> ReviewResult:
        return ReviewResult(
            version_id=row["id"],
            review_status=row["review_status"],
            ingestion_status=row["ingestion_status"],
            version_status=row["version_status"],
            snapshot_sha256=row["snapshot_sha256"],
            approved_snapshot_sha256=row["approved_snapshot_sha256"],
            changed=changed,
        )
