import json
import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import MetadataCorrection

GUIDE = "https://synthetic.example/connection-guide"


def container(tmp_path):
    return build_container(Settings(project_root=Path(tmp_path)))


def review_app(tmp_path, url=GUIDE, setup=""):
    c = container(tmp_path)
    c.sources.queue_for_review(c.discovery.add_source(url).source_id)
    script = (
        "from pathlib import Path\n"
        "import streamlit as st\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        "from gridlens.ui.review import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        f"{setup}"
        "render(c)\n"
    )
    return AppTest.from_string(script).run()


def button(app, label):
    return next(item for item in app.button if item.label == label)


def rows(tmp_path, sql):
    with sqlite3.connect(tmp_path / "data/fixture/research.sqlite3") as connection:
        return connection.execute(sql).fetchall()


def captured(tmp_path, reviewer="Researcher A"):
    app = review_app(tmp_path)
    app.text_input(key="review_reviewer").set_value(reviewer)
    button(app, "Capture document").click().run()
    assert not app.exception
    return app


def test_capture_preview_and_approve_saves_reviewer_once(tmp_path):
    app = captured(tmp_path)
    assert any("waiting for review" in item.value for item in app.success)
    assert any("fictional operator" in item.value for item in app.text)
    assert any("Open original" == item.label for item in app.get("link_button"))
    button(app, "Approve").click().run()
    assert not app.exception
    assert any("Approved" in item.value for item in app.success)
    [(status, approved, current)] = rows(
        tmp_path,
        "SELECT review_status, approved_snapshot_sha256, snapshot_sha256 FROM document_versions",
    )
    assert status == "approved" and approved == current
    assert rows(tmp_path, "SELECT action, reviewer_label FROM review_events") == [
        ("approve", "Researcher A")
    ]

    app.run()
    app.run()
    assert not app.exception
    assert len(rows(tmp_path, "SELECT id FROM review_events")) == 1
    assert len(rows(tmp_path, "SELECT id FROM document_versions")) == 1


def test_reviewer_label_is_required(tmp_path):
    app = captured(tmp_path, reviewer="")
    button(app, "Approve").click().run()
    assert any("reviewer label" in item.value for item in app.error)
    assert rows(tmp_path, "SELECT review_status FROM document_versions") == [("pending",)]
    assert rows(tmp_path, "SELECT id FROM review_events") == []


def test_reject_requires_reason_and_saves_exact_input(tmp_path):
    app = captured(tmp_path)
    button(app, "Reject").click().run()
    assert any("reason before rejecting" in item.value for item in app.error)
    assert rows(tmp_path, "SELECT id FROM review_events") == []

    app.text_area[0].set_value("Wrong jurisdiction for NZ research")
    button(app, "Reject").click().run()
    assert not app.exception
    assert rows(tmp_path, "SELECT action, reviewer_label, reason FROM review_events") == [
        ("reject", "Researcher A", "Wrong jurisdiction for NZ research")
    ]
    app.run()
    assert len(rows(tmp_path, "SELECT id FROM review_events")) == 1
    assert any(item.label == "Reopen for review" for item in app.button)


def test_stale_preview_requires_reload_before_approval(tmp_path):
    app = captured(tmp_path)
    service = container(tmp_path)
    [(version_id, seen_hash, metadata)] = rows(
        tmp_path, "SELECT id, snapshot_sha256, metadata_json FROM document_versions"
    )
    meta = json.loads(metadata)
    service.review.update_metadata(
        version_id,
        seen_hash,
        MetadataCorrection(
            title=meta["title"],
            publisher="Changed elsewhere",
            jurisdiction="NZ",
            source_type="technical",
        ),
    )

    # The click comes from the page rendered before the change.
    button(app, "Approve").click().run()
    assert not app.exception
    assert any("changed after you opened it" in item.value for item in app.warning)
    assert button(app, "Approve").disabled
    assert rows(tmp_path, "SELECT review_status FROM document_versions") == [("pending",)]
    assert rows(tmp_path, "SELECT id FROM review_events") == []

    button(app, "Reload preview").click().run()
    assert not app.warning
    button(app, "Approve").click().run()
    [(status, approved, current)] = rows(
        tmp_path,
        "SELECT review_status, approved_snapshot_sha256, snapshot_sha256 FROM document_versions",
    )
    assert status == "approved" and approved == current != seen_hash


def test_unreadable_snapshot_cannot_be_approved(tmp_path):
    app = captured(tmp_path)
    [(raw_path,)] = rows(tmp_path, "SELECT raw_path FROM document_versions")
    (tmp_path / "data/fixture" / raw_path).write_bytes(b"tampered")
    button(app, "Approve").click().run()
    assert any("no longer matches" in item.value for item in app.error)
    assert button(app, "Approve").disabled
    assert rows(tmp_path, "SELECT review_status FROM document_versions") == [("pending",)]


def test_empty_document_capture_creates_no_version(tmp_path):
    app = review_app(tmp_path, "https://synthetic.example/empty")
    button(app, "Capture document").click().run()
    assert any("No readable text" in item.value for item in app.error)
    assert rows(tmp_path, "SELECT id FROM document_versions") == []
    assert rows(tmp_path, "SELECT access_status FROM sources") == [("failed",)]


def test_metadata_correction_updates_hash_bound_to_approval(tmp_path):
    app = captured(tmp_path)
    [(original_hash,)] = rows(tmp_path, "SELECT snapshot_sha256 FROM document_versions")
    app.selectbox[0].set_value("GLOBAL")
    app.text_input[3].set_value("2026-01-15")
    button(app, "Save metadata").click().run()
    assert not app.exception
    assert any("Metadata saved" in item.value for item in app.success)
    [(new_hash, metadata, published_at)] = rows(
        tmp_path, "SELECT snapshot_sha256, metadata_json, published_at FROM document_versions"
    )
    assert new_hash != original_hash
    assert json.loads(metadata)["jurisdiction"] == "GLOBAL"
    assert published_at == "2026-01-15"
    assert not app.warning
    button(app, "Approve").click().run()
    assert rows(tmp_path, "SELECT approved_snapshot_sha256 FROM document_versions") == [(new_hash,)]


def test_revoke_and_reopen_from_review_page(tmp_path):
    app = captured(tmp_path)
    button(app, "Approve").click().run()
    app.text_input(key=next(k.key for k in app.text_input if "revoke" in k.key)).set_value(
        "Source withdrawn"
    )
    button(app, "Revoke approval").click().run()
    assert rows(tmp_path, "SELECT review_status FROM document_versions") == [("revoked",)]
    button(app, "Reopen for review").click().run()
    assert not app.exception
    assert rows(
        tmp_path, "SELECT review_status, approved_snapshot_sha256 FROM document_versions"
    ) == [("pending", None)]
    assert rows(tmp_path, "SELECT action, reason FROM review_events ORDER BY rowid") == [
        ("approve", None),
        ("revoke", "Source withdrawn"),
        ("reopen", None),
    ]


def test_approval_indexes_once_and_rerun_does_not_reindex(tmp_path):
    app = captured(tmp_path)
    button(app, "Approve").click().run()
    assert not app.exception
    assert any("Indexed" in item.value and "searchable" in item.value for item in app.success)
    assert rows(tmp_path, "SELECT ingestion_status, version_status FROM document_versions") == [
        ("ready", "active")
    ]
    app.run()
    app.run()
    assert rows(tmp_path, "SELECT status FROM ingestion_runs") == [("completed",)]
    assert not any(item.label == "Retry indexing" for item in app.button)


def test_retry_indexing_for_approved_but_unindexed_version(tmp_path):
    app = captured(tmp_path)
    service = container(tmp_path)
    [(version_id, snapshot)] = rows(tmp_path, "SELECT id, snapshot_sha256 FROM document_versions")
    service.review.approve(version_id, snapshot, "Researcher A")
    app.run()
    button(app, "Retry indexing").click().run()
    assert not app.exception
    assert any("Retried. Indexed" in item.value for item in app.success)
    assert rows(tmp_path, "SELECT ingestion_status FROM document_versions") == [("ready",)]


def test_indexing_failure_keeps_approval_and_offers_retry(tmp_path):
    setup = (
        "from gridlens.providers.fakes import FakeEmbeddingProvider\n"
        "if st.session_state.get('fail_indexing', True):\n"
        "    c.ingestion.embeddings = FakeEmbeddingProvider('LOCAL_MODEL_MISSING')\n"
    )
    app = review_app(tmp_path, setup=setup)
    app.text_input(key="review_reviewer").set_value("Researcher A")
    button(app, "Capture document").click().run()
    button(app, "Approve").click().run()
    assert not app.exception
    assert any("Indexing failed (LOCAL_MODEL_MISSING)" in item.value for item in app.warning)
    assert rows(tmp_path, "SELECT review_status, ingestion_status FROM document_versions") == [
        ("approved", "failed")
    ]
    app.session_state["fail_indexing"] = False
    button(app, "Retry indexing").click().run()
    assert any("Retried. Indexed" in item.value for item in app.success)
    assert rows(tmp_path, "SELECT status FROM ingestion_runs ORDER BY attempt") == [
        ("failed",),
        ("completed",),
    ]
