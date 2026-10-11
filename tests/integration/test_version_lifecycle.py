import hashlib
import json
from pathlib import Path

import pytest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import FetchedDocument, MetadataCorrection, RetrievalFilters
from gridlens.errors import AppError
from gridlens.services.citations import source_statuses

URL = "https://synthetic.example/lifecycle"


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
def app(tmp_path):
    container = build_container(Settings(project_root=Path(tmp_path)))
    container.snapshots.fetcher = Fetcher()
    return container


def publish_text(app, source_id, text, key):
    app.snapshots.fetcher.body = f"<main><p>{text}</p></main>".encode()
    preview = app.snapshots.capture(source_id)
    if preview.reused:
        return preview
    current = preview.snapshot_sha256
    if preview.metadata["jurisdiction"] != "NZ":
        current = app.review.update_metadata(
            preview.version_id,
            current,
            MetadataCorrection(title="Lifecycle guide", jurisdiction="NZ", source_type="policy"),
        ).snapshot_sha256
    app.review.approve(preview.version_id, current, "Researcher")
    assert app.ingestion.ingest(preview.version_id, key).status == "completed"
    return preview


def version(app, version_id):
    return app.sources.get_version(version_id)


def eligible(app):
    return {v["id"] for v in app.research.eligible_versions(app.ingestion.fingerprint, None)}


def ask(app, key):
    return app.answer_service.ask(
        "How does the synthetic process start?", RetrievalFilters(), key, app.answers
    )


class BrokenDelete:
    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def delete_version(self, version_id):
        raise RuntimeError("synthetic index cleanup failure")


def test_v1_v2_revoke_lifecycle(app):
    source_id = app.discovery.add_source(URL).source_id
    v1 = publish_text(app, source_id, "The synthetic process starts with an application.", "k1")
    first_answer = ask(app, "q1")
    assert first_answer.execution_status == "completed"
    v1_quote = first_answer.citations[0]["quote"]

    # Same content: refresh is a no-op even though the reviewer corrected the metadata.
    assert app.snapshots.capture(source_id).reused
    assert len(app.research.list_versions()) == 1

    # Changed content: a pending candidate; v1 stays searchable meanwhile.
    app.snapshots.fetcher.body = (
        b"<main><p>The synthetic process starts with an application and a fee.</p></main>"
    )
    v2 = app.snapshots.capture(source_id)
    assert not v2.reused
    assert version(app, v2.version_id)["review_status"] == "pending"
    assert version(app, v2.version_id)["approved_snapshot_sha256"] is None  # no inherited approval
    assert v2.metadata["jurisdiction"] == "NZ"  # reviewed labels carried forward
    assert eligible(app) == {v1.version_id}

    app.review.approve(v2.version_id, v2.snapshot_sha256, "Researcher")
    assert eligible(app) == {v1.version_id}  # approved but not yet indexed
    assert app.ingestion.ingest(v2.version_id, "k2").status == "completed"
    assert version(app, v1.version_id)["version_status"] == "superseded"
    assert eligible(app) == {v2.version_id}

    # The old answer keeps its text and quote; its status is recomputed on read.
    replayed = app.answer_service.replay("q1")
    assert replayed.citations[0]["quote"] == v1_quote
    assert replayed.citations[0]["source"]["version_id"] == v1.version_id
    fp = app.ingestion.fingerprint
    assert source_statuses(app.db, [v1.version_id], fp) == {v1.version_id: "superseded"}

    second_answer = ask(app, "q2")
    assert second_answer.citations[0]["source"]["version_id"] == v2.version_id

    # Revoke v2 while vector cleanup fails: still excluded, and v1 is not resurrected.
    app.ingestion.vectors = BrokenDelete(app.ingestion.vectors)
    app.review.revoke(v2.version_id, "Researcher", "Withdrawn")
    assert app.ingestion.purge_vectors(v2.version_id) is False
    assert eligible(app) == set()
    assert version(app, v1.version_id)["version_status"] == "superseded"
    assert source_statuses(app.db, [v2.version_id], fp) == {v2.version_id: "revoked"}
    after = ask(app, "q3")
    assert after.evidence_status == "insufficient"
    assert app.retrieval.retrieve("synthetic process", RetrievalFilters()).chunks == []


def test_approved_metadata_correction_needs_new_review(app):
    source_id = app.discovery.add_source(URL).source_id
    v1 = publish_text(app, source_id, "The synthetic process starts with an application.", "k1")
    revised = app.review.revise_metadata(
        v1.version_id,
        MetadataCorrection(title="Lifecycle guide", jurisdiction="GLOBAL", source_type="policy"),
    )
    assert revised.version_id != v1.version_id
    assert (revised.review_status, revised.approved_snapshot_sha256) == ("pending", None)
    assert revised.snapshot_sha256 != version(app, v1.version_id)["snapshot_sha256"]
    assert eligible(app) == {v1.version_id}  # old approval still serves until re-review
    new_row = version(app, revised.version_id)
    old_row = version(app, v1.version_id)
    assert new_row["raw_path"] == old_row["raw_path"]
    assert json.loads(new_row["metadata_json"])["jurisdiction"] == "GLOBAL"
    assert app.review.load_snapshot(revised.version_id)  # integrity verified for the new hash
    with pytest.raises(AppError) as raised:
        app.review.revise_metadata(
            v1.version_id,
            MetadataCorrection(
                title="Lifecycle guide", jurisdiction="GLOBAL", source_type="policy"
            ),
        )
    assert raised.value.code == "VERSION_DUPLICATE"


def test_changed_hash_after_approval_cannot_be_indexed(app):
    source_id = app.discovery.add_source(URL).source_id
    app.snapshots.fetcher.body = b"<main><p>Synthetic text for tampering checks.</p></main>"
    preview = app.snapshots.capture(source_id)
    app.review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    with app.db.transaction() as c:
        c.execute(
            "UPDATE document_versions SET snapshot_sha256=? WHERE id=?",
            ("0" * 64, preview.version_id),
        )
    with pytest.raises(AppError) as raised:
        app.ingestion.ingest(preview.version_id, "k-tampered")
    assert raised.value.code == "REVIEW_REQUIRED"
    assert eligible(app) == set()
