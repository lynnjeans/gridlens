import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import FetchedDocument, MetadataCorrection, RetrievalFilters
from gridlens.services.export import ExportSelection, md, safe_url

EVIL_TITLE = "</a><script>alert(1)</script> **bold** [x](javascript:alert(1)) # 并网指南"


class Fetcher:
    def __init__(self):
        self.body = b""

    def fetch(self, url):
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            content_type="text/html",
            body=self.body,
            raw_sha256=hashlib.sha256(self.body).hexdigest(),
            fetched_at="2026-10-12T00:00:00+00:00",
            redirect_count=0,
        )


@pytest.fixture
def world(tmp_path):
    app = build_container(Settings(project_root=Path(tmp_path)))
    app.snapshots.fetcher = Fetcher()
    counter = iter(range(1000))

    def capture(name, text, *, title=None, approve=True, ingest=True):
        source_id = app.discovery.add_source(f"https://synthetic.example/{name}").source_id
        app.snapshots.fetcher.body = f"<main><p>{text}</p></main>".encode()
        preview = app.snapshots.capture(source_id)
        current = app.review.update_metadata(
            preview.version_id,
            preview.snapshot_sha256,
            MetadataCorrection(title=title or name, jurisdiction="NZ", source_type="policy"),
        ).snapshot_sha256
        if approve:
            app.review.approve(preview.version_id, current, "Researcher")
        if ingest:
            app.ingestion.ingest(preview.version_id, f"k{next(counter)}")
        return source_id, preview.version_id

    ids = {}
    _, ids["current"] = capture(
        "current", "并网申请需要提交负荷资料 current evidence text.", title=EVIL_TITLE
    )
    ask = lambda q, key: app.answer_service.ask(  # noqa: E731
        q, RetrievalFilters(), key, app.answers
    )
    ids["qa_current"] = ask("# heading? | table | current evidence", "q-current").qa_id

    _, ids["revoked"] = capture("revoked", "REVOKED QUOTE TEXT stays out.")
    ids["qa_revoked"] = ask("What does the revoked source say?", "q-revoked").qa_id
    app.review.revoke(ids["revoked"], "Researcher", "Withdrawn by publisher")

    source_id, ids["superseded"] = capture("edition", "SUPERSEDED QUOTE TEXT old edition.")
    ids["qa_superseded"] = ask("What does the old edition say?", "q-old").qa_id
    app.snapshots.fetcher.body = b"<main><p>New edition text.</p></main>"
    new = app.snapshots.capture(source_id)
    app.review.approve(new.version_id, new.snapshot_sha256, "Researcher")
    app.ingestion.ingest(new.version_id, "k-new")
    ids["new_edition"] = new.version_id

    _, ids["pending"] = capture("pending", "PENDING SECRET BODY", approve=False, ingest=False)
    _, ids["rejected"] = capture("rejected", "REJECTED BODY", approve=False, ingest=False)
    app.review.reject(ids["rejected"], "Researcher", "Off topic <b>bold</b>")
    with app.db.transaction() as c:  # a lead whose stored URL is not HTTP(S)
        row = c.execute(
            "SELECT metadata_json FROM document_versions WHERE id=?", (ids["pending"],)
        ).fetchone()
        meta = json.loads(row[0]) | {"original_url": "javascript:alert(1)"}
        c.execute(
            "UPDATE document_versions SET metadata_json=? WHERE id=?",
            (json.dumps(meta), ids["pending"]),
        )
    app.answer_service.ask(
        "Is a 5 MW load allowed? <img src=x onerror=alert(1)>",
        RetrievalFilters(region="US"),
        "q-gap",
        app.answers,
    )
    return app, ids


def export(app, ids):
    selection = ExportSelection(
        version_ids=[
            ids[k]
            for k in ("current", "revoked", "superseded", "new_edition", "pending", "rejected")
        ],
        qa_ids=[ids["qa_current"], ids["qa_revoked"], ids["qa_superseded"]],
    )
    return app.export.export(selection, generated_at=datetime(2026, 10, 12, 1, 0, tzinfo=UTC))


def test_export_boundaries(world):
    app, ids = world
    text = export(app, ids)
    lower = text.lower()
    assert "<script" not in lower and "<img" not in lower and "<b>" not in lower
    assert "](javascript" not in lower and "<javascript" not in lower  # never a link target
    assert "PENDING SECRET BODY" not in text and "REJECTED BODY" not in text
    assert "REVOKED QUOTE TEXT" not in text and "Quote omitted" in text
    assert "Historical answer" in text
    assert "SUPERSEDED QUOTE TEXT" in text and "(superseded version)" in text
    assert "current evidence text" in text and "并网申请" in text and "并网指南" in text
    assert "snapshots/" not in text and "data/fixture" not in text
    assert "bearer" not in lower and "token" not in lower
    assert "link withheld" in text
    assert "Withdrawn by publisher" in text  # review notes are exported
    assert "Warning: synthetic development data" in text
    assert "2026-10-12 01:00 UTC" in text and "NZDT" in text


def test_markdown_structure_is_not_broken_by_user_text(world):
    app, ids = world
    text = export(app, ids)
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings[0] == "# GridLens research log"
    assert all(h.startswith(("# GridLens", "## ", "### ")) for h in headings)
    assert "### \\# heading? \\| table \\| current evidence" in text
    assert not any(line.startswith("|") for line in text.splitlines())
    sections = [h for h in headings if h.startswith("## ")]
    assert sections == [
        "## Current approved sources",
        "## Historical or not current sources",
        "## Leads awaiting review (no document text exported)",
        "## Questions and answers",
        "## Knowledge gaps",
    ]


def test_citations_point_to_their_metadata_and_current_status(world):
    app, ids = world
    text = export(app, ids)
    assert f"[{md(EVIL_TITLE)}](https://synthetic.example/current)" in text
    assert "source revoked" in text and "source superseded" in text and "source current" in text
    app.review.revoke(ids["current"], "Researcher", "Later revoked")
    again = export(app, ids)
    assert "current evidence text" not in again  # status follows the database at export time
    assert "Claim c1 omitted" in again


def test_selection_and_open_gaps(world):
    app, ids = world
    only_gaps = app.export.export(ExportSelection())
    assert "## Knowledge gaps" in only_gaps and "Is a 5 MW load allowed" in only_gaps
    assert "&lt;img" in only_gaps
    assert "## Questions and answers" not in only_gaps
    none = app.export.export(ExportSelection(include_open_gaps=False))
    assert "## " not in none


def test_url_and_escape_helpers():
    assert safe_url("https://example.org/a b") is None
    assert safe_url("ftp://example.org") is None
    assert safe_url("https://example.org/x(1)") == "https://example.org/x%281%29"
    assert md("a\nb *c*") == "a b \\*c\\*"


def test_export_file_round_trips_as_utf8(world, tmp_path):
    app, ids = world
    path = tmp_path / "log.md"
    path.write_bytes(export(app, ids).encode("utf-8"))
    assert "并网申请" in path.read_text("utf-8")
