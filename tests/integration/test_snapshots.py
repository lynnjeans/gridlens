import hashlib
import json

import pytest

from gridlens.contracts import FetchedDocument, SearchHitDTO
from gridlens.documents.snapshots import SnapshotService, atomic_write
from gridlens.errors import AppError
from gridlens.repositories.sources import SourceRepository


class FakeFetcher:
    def __init__(self, documents=None, error=None):
        self.documents = iter(documents or [])
        self.error = error

    def fetch(self, url):
        if self.error:
            raise self.error
        return next(self.documents)


def fetched(body, *, fetched_at="2026-10-11T00:00:00+00:00", content_type="text/html"):
    return FetchedDocument(
        requested_url="https://example.org/guide",
        final_url="https://example.org/guide",
        content_type=content_type,
        body=body,
        raw_sha256=hashlib.sha256(body).hexdigest(),
        fetched_at=fetched_at,
        redirect_count=0,
    )


def source(db):
    return SourceRepository(db).save_candidate(
        SearchHitDTO(
            title="Public guide",
            url="https://example.org/guide",
            snippet="candidate",
            provider_rank=1,
            publisher="Example operator",
            source_type="technical",
            jurisdiction="NZ",
        ),
        "https://example.org/guide",
    )


def service(db, tmp_path, fetcher, writer=atomic_write):
    return SnapshotService(
        db,
        SourceRepository(db),
        fetcher,
        tmp_path / "data/fixture",
        max_pdf_pages=10,
        pdf_timeout_seconds=5,
        writer=writer,
    )


def test_capture_writes_consistent_files_and_database(db, tmp_path):
    source_id = source(db)
    body = b"<main><h1>Guide</h1><p>Connection applications need 50 MW data.</p></main>"
    preview = service(db, tmp_path, FakeFetcher([fetched(body)])).capture(source_id)
    assert not preview.reused
    assert preview.review_status == "pending"
    row = SourceRepository(db).get_version_by_snapshot(source_id, preview.snapshot_sha256)
    raw_path = tmp_path / "data/fixture" / row["raw_path"]
    segments_path = tmp_path / "data/fixture" / row["segments_path"]
    assert raw_path.read_bytes() == body
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == row["raw_sha256"]
    assert json.loads(segments_path.read_text())[0]["locator"]["paragraph_index"] == 1
    assert SourceRepository(db).get_source(source_id)["access_status"] == "readable"


def test_same_snapshot_reuses_version_despite_fetch_time_and_navigation_change(db, tmp_path):
    source_id = source(db)
    first = fetched(b"<nav>first</nav><main><p>Stable text.</p></main>")
    second = fetched(
        b"<nav>changed</nav><main><p>Stable text.</p></main>",
        fetched_at="2026-10-12T00:00:00+00:00",
    )
    snapshots = service(db, tmp_path, FakeFetcher([first, second]))
    initial = snapshots.capture(source_id)
    repeated = snapshots.capture(source_id)
    assert repeated.reused
    assert repeated.version_id == initial.version_id
    assert repeated.raw_sha256 == initial.raw_sha256
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 1


def test_pdf_capture_dispatch_preserves_physical_pages(db, tmp_path, fixtures_dir):
    source_id = source(db)
    body = (fixtures_dir / "readable.pdf").read_bytes()
    preview = service(
        db, tmp_path, FakeFetcher([fetched(body, content_type="application/pdf")])
    ).capture(source_id)
    assert [segment.locator.file_page for segment in preview.segments] == [1, 2]
    row = SourceRepository(db).get_version_by_snapshot(source_id, preview.snapshot_sha256)
    assert row["raw_path"].endswith("raw.pdf")


def test_content_or_reviewed_metadata_change_creates_new_pending_version(db, tmp_path):
    source_id = source(db)
    snapshots = service(
        db,
        tmp_path,
        FakeFetcher(
            [
                fetched(b"<main><p>Version one.</p></main>"),
                fetched(b"<main><p>Version two.</p></main>"),
                fetched(b"<main><p>Version two.</p></main>"),
            ]
        ),
    )
    first = snapshots.capture(source_id)
    second = snapshots.capture(source_id)
    assert second.snapshot_sha256 != first.snapshot_sha256
    with db.transaction() as connection:
        connection.execute(
            "UPDATE sources SET publisher='Corrected publisher' WHERE id=?", (source_id,)
        )
    third = snapshots.capture(source_id)
    assert third.snapshot_sha256 != second.snapshot_sha256
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT review_status, version_status FROM document_versions"
        ).fetchall()
    assert [tuple(row) for row in rows] == [("pending", "candidate")] * 3


def test_write_failure_removes_partial_files_and_database_row(db, tmp_path):
    source_id = source(db)
    calls = 0

    def failing_writer(path, content):
        nonlocal calls
        calls += 1
        atomic_write(path, content)
        if calls == 2:
            raise OSError("synthetic disk failure")

    with pytest.raises(AppError) as raised:
        service(
            db,
            tmp_path,
            FakeFetcher([fetched(b"<main><p>Text.</p></main>")]),
            failing_writer,
        ).capture(source_id)
    assert raised.value.code == "SNAPSHOT_SAVE_FAILED"
    assert not list((tmp_path / "data/fixture/snapshots").rglob("raw.html"))
    assert not list((tmp_path / "data/fixture/snapshots").rglob("segments.json"))
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 0


def test_fetch_or_parse_failure_marks_lead_failed_without_version(db, tmp_path):
    source_id = source(db)
    with pytest.raises(AppError):
        service(
            db,
            tmp_path,
            FakeFetcher(error=AppError("FETCH_TIMEOUT", "synthetic timeout")),
        ).capture(source_id)
    assert SourceRepository(db).get_source(source_id)["access_status"] == "failed"
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 0
