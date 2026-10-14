"""Immutable, reviewable snapshots derived from bounded captures."""

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from gridlens.contracts import FetchedDocument, ParsedSegment, VersionPreview
from gridlens.db import Database, now
from gridlens.documents.html import parse_html
from gridlens.documents.metadata import html_hints, pdf_hints, suggest
from gridlens.documents.pdf import parse_pdf_document, read_pdf_info
from gridlens.errors import AppError
from gridlens.repositories.sources import SourceRepository

PARSER_VERSIONS = {"text/html": "html-v1", "application/pdf": "pypdf-v1"}
REVIEWED_METADATA_KEYS = (
    "title",
    "publisher",
    "published_at",
    "jurisdiction",
    "source_type",
    "original_url",
    "final_url",
    "content_type",
)
# Human-reviewed labels carried into refreshed snapshots (URLs/type come from the fetch).
REVIEWED_LABEL_KEYS = ("title", "publisher", "published_at", "jurisdiction", "source_type")
AtomicWriter = Callable[[Path, bytes], None]


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class SnapshotService:
    def __init__(
        self,
        db: Database,
        sources: SourceRepository,
        fetcher,
        snapshot_root: Path,
        *,
        max_pdf_pages: int,
        pdf_timeout_seconds: float,
        writer: AtomicWriter = atomic_write,
    ):
        self.db = db
        self.sources = sources
        self.fetcher = fetcher
        self.snapshot_root = snapshot_root.resolve()
        self.max_pdf_pages = max_pdf_pages
        self.pdf_timeout_seconds = pdf_timeout_seconds
        self.writer = writer

    def capture(self, source_id: str) -> VersionPreview:
        source = self.sources.get_source(source_id)
        if source is None:
            raise AppError("SOURCE_NOT_FOUND", "The source does not exist.")
        try:
            fetched: FetchedDocument = self.fetcher.fetch(source["original_url"])
            segments, page = self._parse(fetched)
        except AppError:
            self.sources.mark_access(source_id, "failed")
            raise

        metadata = {
            "title": source["title"],
            "publisher": source["publisher"],
            "published_at": self.sources.latest_published_at(source_id),
            "jurisdiction": source["jurisdiction"],
            "source_type": source["source_type"],
            "original_url": source["original_url"],
            "final_url": fetched.final_url,
            "content_type": fetched.content_type,
        }
        hints: dict = {}
        if previous := self.sources.latest_version(source_id):
            # A refresh keeps the reviewer's metadata, so identical content is a no-op and
            # only changed content (or a deliberate metadata revision) needs a new review.
            reviewed = json.loads(previous["metadata_json"])
            metadata.update({key: reviewed.get(key) for key in REVIEWED_LABEL_KEYS})
        else:
            # First extraction: fill empty labels from the document itself, marked as hints.
            hints = suggest(fetched.final_url, metadata, page, prefer_page_title=True)
            metadata.update({field: hint["value"] for field, hint in hints.items()})
        serial_segments = [segment.model_dump(mode="json") for segment in segments]
        parser_version = PARSER_VERSIONS[fetched.content_type]
        snapshot_sha256 = snapshot_digest(segments, metadata, parser_version)
        stored_metadata = {**metadata, "parser_version": parser_version}
        if hints:
            stored_metadata["metadata_hints"] = hints
        existing = self.sources.get_version_by_snapshot(source_id, snapshot_sha256)
        if existing:
            self.sources.mark_access(source_id, "readable")
            return self._preview(
                existing,
                self._load_segments(existing),
                json.loads(existing["metadata_json"]),
                reused=True,
            )

        version_id = str(uuid4())
        relative_dir = Path("snapshots") / source_id / snapshot_sha256
        extension = ".html" if fetched.content_type == "text/html" else ".pdf"
        raw_relative = relative_dir / f"raw{extension}"
        segments_relative = relative_dir / "segments.json"
        raw_path = (self.snapshot_root / raw_relative).resolve()
        segments_path = (self.snapshot_root / segments_relative).resolve()
        if not raw_path.is_relative_to(self.snapshot_root) or not segments_path.is_relative_to(
            self.snapshot_root
        ):
            raise AppError("SNAPSHOT_PATH_INVALID", "The snapshot path is invalid.")
        notes = sorted({warning for segment in segments for warning in segment.warnings})
        target_paths = [raw_path, segments_path]
        existed_before = {path: path.exists() for path in target_paths}
        try:
            self.writer(raw_path, fetched.body)
            self.writer(segments_path, canonical_json(serial_segments))
            with self.db.transaction() as connection:
                connection.execute(
                    "INSERT INTO document_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        version_id,
                        source_id,
                        fetched.raw_sha256,
                        snapshot_sha256,
                        str(raw_relative),
                        str(segments_relative),
                        canonical_json(stored_metadata).decode(),
                        metadata["published_at"],
                        fetched.fetched_at,
                        canonical_json(notes).decode(),
                        "pending",
                        "not_started",
                        "candidate",
                        None,
                        None,
                        now(),
                    ),
                )
                connection.execute(
                    "UPDATE sources SET access_status='readable' WHERE id=?", (source_id,)
                )
        except Exception as error:
            for path in target_paths:
                if not existed_before[path]:
                    path.unlink(missing_ok=True)
            if isinstance(error, AppError):
                raise
            raise AppError(
                "SNAPSHOT_SAVE_FAILED", "The document snapshot could not be saved."
            ) from None
        row = self.sources.get_version_by_snapshot(source_id, snapshot_sha256)
        if row is None:
            raise AppError("SNAPSHOT_SAVE_FAILED", "The saved snapshot could not be loaded.")
        return self._preview(row, segments, stored_metadata, reused=False)

    def page_hints(self, version_id: str) -> dict[str, dict]:
        """Hints for a version's empty labels, read from its saved copy (no network)."""
        row = self.sources.get_version(version_id)
        if row is None:
            raise AppError("VERSION_NOT_FOUND", "The document version does not exist.")
        metadata = json.loads(row["metadata_json"])
        path = (self.snapshot_root / row["raw_path"]).resolve()
        if not path.is_relative_to(self.snapshot_root):
            raise AppError("SNAPSHOT_PATH_INVALID", "The snapshot path is invalid.")
        try:
            body = path.read_bytes()
        except OSError:
            raise AppError(
                "SNAPSHOT_READ_FAILED", "The saved snapshot could not be read."
            ) from None
        page = self._page(metadata["content_type"], body)
        url = metadata.get("final_url") or metadata["original_url"]
        return suggest(url, metadata, page, prefer_page_title=False)

    def _parse(self, fetched: FetchedDocument) -> tuple[list[ParsedSegment], dict]:
        if fetched.content_type == "text/html":
            return parse_html(fetched.body), html_hints(fetched.body)
        segments, info = parse_pdf_document(
            fetched.body,
            max_pages=self.max_pdf_pages,
            timeout_seconds=self.pdf_timeout_seconds,
        )
        return segments, pdf_hints(info)

    def _page(self, content_type: str, body: bytes) -> dict:
        if content_type == "text/html":
            return html_hints(body)
        return pdf_hints(read_pdf_info(body, timeout_seconds=self.pdf_timeout_seconds))

    def _load_segments(self, row) -> list[ParsedSegment]:
        path = (self.snapshot_root / row["segments_path"]).resolve()
        if not path.is_relative_to(self.snapshot_root):
            raise AppError("SNAPSHOT_PATH_INVALID", "The snapshot path is invalid.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [ParsedSegment.model_validate(item) for item in data]
        except (OSError, ValueError):
            raise AppError(
                "SNAPSHOT_READ_FAILED", "The saved snapshot could not be read."
            ) from None

    @staticmethod
    def _preview(row, segments, metadata, *, reused: bool) -> VersionPreview:
        return VersionPreview(
            version_id=row["id"],
            source_id=row["source_id"],
            snapshot_sha256=row["snapshot_sha256"],
            raw_sha256=row["raw_sha256"],
            content_type=metadata["content_type"],
            segments=segments,
            metadata=metadata,
            extraction_notes=json.loads(row["extraction_notes_json"]),
            reused=reused,
        )


def canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def snapshot_digest(segments: list[ParsedSegment], metadata: dict, parser_version: str) -> str:
    identity = {
        "segments": [
            segment.model_dump(mode="json", exclude={"segment_id"}) for segment in segments
        ],
        "reviewed_metadata": {key: metadata.get(key) for key in REVIEWED_METADATA_KEYS},
        "parser_version": parser_version,
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()
