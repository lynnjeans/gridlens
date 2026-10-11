import json
import sqlite3

import pytest

from gridlens.contracts import SearchHitDTO
from gridlens.db import Database, now
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository


def candidate(db):
    return SourceRepository(db).save_candidate(
        SearchHitDTO(
            title="Synthetic source",
            url="https://synthetic.example",
            snippet="",
            provider_rank=1,
        ),
        "https://synthetic.example",
    )


def version(db, source_id, identifier="v1", **change):
    row = dict(
        id=identifier,
        source_id=source_id,
        raw_sha256="raw",
        snapshot_sha256=identifier,
        raw_path="snapshots/raw",
        segments_path="snapshots/segments",
        metadata_json=json.dumps({"jurisdiction": "NZ"}),
        published_at=None,
        fetched_at=now(),
        extraction_notes_json="[]",
        review_status="approved",
        ingestion_status="ready",
        version_status="active",
        approved_snapshot_sha256=identifier,
        index_fingerprint="fixture",
        created_at=now(),
    )
    row.update(change)
    with db.transaction() as c:
        c.execute(
            f"INSERT INTO document_versions ({','.join(row)}) "
            f"VALUES ({','.join('?' for _ in row)})",
            tuple(row.values()),
        )


def test_initialize_idempotent_persistent_and_parameterized(db):
    repo = SourceRepository(db)
    title = "x'); DROP TABLE sources; --"
    hit = SearchHitDTO(title=title, url="https://synthetic.example", snippet="", provider_rank=1)
    identifier = repo.save_candidate(hit, hit.url)
    assert repo.save_candidate(hit, hit.url) == identifier
    db.initialize()
    reopened = Database(db.path)
    assert SourceRepository(reopened).list_sources()[0]["title"] == title
    with reopened.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_version_one_database_upgrades_in_place(tmp_path):
    from importlib.resources import files

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as c:
        c.executescript(files("gridlens").joinpath("migrations/001_initial.sql").read_text())
        c.execute("INSERT INTO schema_migrations VALUES (1, 'then')")
        c.execute(
            "INSERT INTO sources VALUES ('s','https://a.example','https://a.example','t',NULL,"
            "'unknown','NZ','[]','unknown','then')"
        )
    database = Database(path)
    database.initialize()
    database.initialize()
    with database.connect() as c:
        assert [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY 1")] == [
            1,
            2,
        ]
        columns = {r["name"] for r in c.execute("PRAGMA table_info(chunks)")}
        assert "source_segment_ids_json" in columns
        assert c.execute("SELECT title FROM sources").fetchone()[0] == "t"


def test_foreign_key_unique_active_and_transaction_rollback(db):
    source_id = candidate(db)
    version(db, source_id)
    with pytest.raises(sqlite3.IntegrityError):
        version(db, source_id, "v2")
    with pytest.raises(sqlite3.IntegrityError):
        version(db, "missing-source", "missing-version")
    with pytest.raises(RuntimeError), db.transaction() as c:
        c.execute("UPDATE sources SET title='changed' WHERE id=?", (source_id,))
        raise RuntimeError("Simulate crash before commit")
    assert SourceRepository(db).list_sources()[0]["title"] == "Synthetic source"


@pytest.mark.parametrize(
    "change",
    [
        {"review_status": "pending"},
        {"review_status": "rejected"},
        {"review_status": "revoked"},
        {"ingestion_status": "failed", "version_status": "candidate"},
        {"version_status": "superseded"},
        {"approved_snapshot_sha256": "wrong-hash"},
        {"index_fingerprint": "other-config"},
        {"metadata_json": '{"jurisdiction":"US"}'},
    ],
)
def test_ineligible_versions_are_excluded(db, change):
    version(db, candidate(db), **change)
    assert ResearchRepository(db).eligible_versions("fixture") == []


def test_approved_metadata_drives_eligibility(db):
    source_id = candidate(db)
    version(db, source_id)
    with db.transaction() as c:
        c.execute("UPDATE sources SET jurisdiction='US' WHERE id=?", (source_id,))
    assert len(ResearchRepository(db).eligible_versions("fixture")) == 1


def test_open_gap_uniqueness_and_resolution_note(db):
    with db.transaction() as c:
        c.execute(
            "INSERT INTO qa_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "q",
                "op",
                "Question",
                "{}",
                "completed",
                "insufficient",
                "{}",
                "[]",
                "[]",
                None,
                None,
                None,
                "v1",
                None,
                now(),
                0,
                "{}",
                None,
            ),
        )
        row = (
            "gap1",
            "q",
            "same-key",
            "Question",
            "{}",
            "no_evidence",
            "Needed",
            "[]",
            "open",
            None,
            now(),
            now(),
        )
        c.execute("INSERT INTO knowledge_gaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as c:
        c.execute("INSERT INTO knowledge_gaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("gap2", *row[1:]))
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as c:
        c.execute("UPDATE knowledge_gaps SET status='resolved' WHERE id='gap1'")
    with db.transaction() as c:
        c.execute("UPDATE knowledge_gaps SET status='dismissed' WHERE id='gap1'")
        c.execute("INSERT INTO knowledge_gaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("gap2", *row[1:]))
