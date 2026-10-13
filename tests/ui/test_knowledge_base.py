import hashlib
import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import FetchedDocument, RetrievalFilters, SearchHitDTO
from gridlens.documents.snapshots import SnapshotService
from gridlens.providers.fakes import FakeEmbeddingProvider


class Fetcher:
    def __init__(self):
        self.bodies = {}

    def fetch(self, url):
        body = self.bodies[url]
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            content_type="text/html",
            body=body,
            raw_sha256=hashlib.sha256(body).hexdigest(),
            fetched_at="2026-10-12T00:00:00+00:00",
            redirect_count=0,
        )


class Seed:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.app = build_container(Settings(project_root=Path(tmp_path)))
        self.fetcher = Fetcher()
        self.snapshots = SnapshotService(
            self.app.db,
            self.app.sources,
            self.fetcher,
            self.app.settings.data_dir,
            max_pdf_pages=5,
            pdf_timeout_seconds=5,
        )
        self.n = 0

    def source(self, name):
        url = f"https://synthetic.example/{name}"
        hit = SearchHitDTO(title=name, url=url, snippet="s", provider_rank=1, jurisdiction="NZ")
        return self.app.sources.save_candidate(hit, url), url

    def capture(self, source_id, url, text):
        self.fetcher.bodies[url] = f"<main><p>{text}</p></main>".encode()
        return self.snapshots.capture(source_id)

    def version(self, name, *, approve=True, ingest=True):
        source_id, url = self.source(name)
        preview = self.capture(source_id, url, f"Grid connection text for {name}.")
        if approve:
            self.app.review.approve(preview.version_id, preview.snapshot_sha256, "Seeder")
        if ingest:
            self.n += 1
            self.app.ingestion.ingest(preview.version_id, f"seed-{self.n}")
        return preview.version_id


def seeded(tmp_path):
    seed = Seed(tmp_path)
    ids = {
        "searchable": seed.version("searchable"),
        "pending": seed.version("pending", approve=False, ingest=False),
        "not_indexed": seed.version("not-indexed", ingest=False),
        "revoked": seed.version("revoked"),
    }
    rejected = seed.version("rejected", approve=False, ingest=False)
    seed.app.review.reject(rejected, "Seeder", "Off topic")
    ids["rejected"] = rejected
    seed.app.review.revoke(ids["revoked"], "Seeder", "Withdrawn")
    failed = seed.version("failed", ingest=False)
    seed.app.ingestion.embeddings = FakeEmbeddingProvider("LOCAL_MODEL_MISSING")
    seed.app.ingestion.ingest(failed, "seed-failed")
    seed.app.ingestion.embeddings = FakeEmbeddingProvider()
    ids["failed"] = failed
    source_id, url = seed.source("edition")
    old = seed.capture(source_id, url, "Old edition text.")
    seed.app.review.approve(old.version_id, old.snapshot_sha256, "Seeder")
    seed.app.ingestion.ingest(old.version_id, "seed-old")
    new = seed.capture(source_id, url, "New edition text.")
    seed.app.review.approve(new.version_id, new.snapshot_sha256, "Seeder")
    seed.app.ingestion.ingest(new.version_id, "seed-new")
    ids["superseded"], ids["current"] = old.version_id, new.version_id
    processing = seed.version("processing", ingest=False)
    with seed.app.db.transaction() as c:
        c.execute(
            "INSERT INTO ingestion_runs VALUES ('run-p','op-p',?,'embedding','processing',1,4,1,"
            "'2026-10-12T00:00:00+00:00',NULL,NULL)",
            (processing,),
        )
        c.execute(
            "UPDATE document_versions SET ingestion_status='processing' WHERE id=?", (processing,)
        )
    ids["processing"] = processing
    return seed, ids


def kb_app(tmp_path, version_id=None):
    script = (
        "from pathlib import Path\n"
        "import streamlit as st\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        "from gridlens.ui.knowledge_base import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        + (f"st.session_state.setdefault('kb_version_id', {version_id!r})\n" if version_id else "")
        + "render(c)\n"
    )
    return AppTest.from_string(script).run()


def button(app, label):
    return next(item for item in app.button if item.label == label)


def rows(tmp_path, sql, *args):
    with sqlite3.connect(tmp_path / "data/fixture/research.sqlite3") as c:
        return c.execute(sql, args).fetchall()


def table(app):
    frame = app.dataframe[0].value
    return {row["Title"]: row for row in frame.to_dict("records")}


def test_overview_separates_all_states(tmp_path):
    seed, ids = seeded(tmp_path)
    app = kb_app(tmp_path)
    assert not app.exception
    data = table(app)
    assert data["searchable"]["Status"] == "Searchable"
    assert data["searchable"]["Searchable"] == "yes"
    expected = {
        "pending": "Waiting for review",
        "rejected": "Rejected",
        "revoked": "Approval revoked · not searchable",
        "not-indexed": "Approved · not indexed yet",
        "failed": "Approved · indexing failed (LOCAL_MODEL_MISSING)",
        "processing": "Approved · indexing (embedding)",
    }
    for title, status in expected.items():
        assert data[title]["Status"] == status
        assert data[title]["Searchable"] == "no"
    edition = [r for r in app.dataframe[0].value.to_dict("records") if r["Title"] == "edition"]
    assert sorted(r["Status"] for r in edition) == [
        "Older version: a newer one replaced it",
        "Searchable",
    ]
    assert any("2 searchable" in c.value and "1 awaiting review" in c.value for c in app.caption)
    assert any("3 approved, not searchable" in c.value for c in app.caption)


def test_failed_version_retry_uses_service_with_fresh_operation_key(tmp_path):
    seed, ids = seeded(tmp_path)
    app = kb_app(tmp_path, ids["failed"])
    assert any("1/" in m.value or "0/" in m.value for m in app.markdown)
    button(app, "Retry indexing").click().run()
    assert not app.exception
    assert any("Indexed" in s.value for s in app.success)
    runs = rows(
        tmp_path,
        "SELECT operation_key, status FROM ingestion_runs WHERE version_id=? ORDER BY attempt",
        ids["failed"],
    )
    assert runs[0] == ("seed-failed", "failed")
    assert runs[1][0].startswith("kb-retry-") and runs[1][1] == "completed"
    assert table(app)["failed"]["Status"] == "Searchable"
    app.run()
    assert (
        len(rows(tmp_path, "SELECT id FROM ingestion_runs WHERE version_id=?", ids["failed"])) == 2
    )


def test_processing_version_cannot_be_resubmitted(tmp_path):
    seed, ids = seeded(tmp_path)
    app = kb_app(tmp_path, ids["processing"])
    assert button(app, "Retry indexing").disabled
    assert any("1/4 chunk(s)" in m.value for m in app.markdown)
    assert any("in progress" in i.value for i in app.info)


def test_revoke_requires_reviewer_and_matches_retrieval_eligibility(tmp_path):
    seed, ids = seeded(tmp_path)
    app = kb_app(tmp_path, ids["searchable"])
    button(app, "Revoke approval").click().run()
    assert any("reviewer label" in e.value for e in app.error)
    assert rows(
        tmp_path, "SELECT review_status FROM document_versions WHERE id=?", ids["searchable"]
    ) == [("approved",)]

    app.text_input(key="kb_reviewer").set_value("Researcher B")
    app.text_input(key=f"kb-reason-{ids['searchable']}").set_value("Superseded policy")
    button(app, "Revoke approval").click().run()
    assert not app.exception
    assert table(app)["searchable"]["Status"] == "Approval revoked · not searchable"
    events = rows(
        tmp_path,
        "SELECT action, reviewer_label, reason FROM review_events "
        "WHERE version_id=? AND action='revoke'",
        ids["searchable"],
    )
    assert events == [("revoke", "Researcher B", "Superseded policy")]
    context = seed.app.retrieval.retrieve("grid connection text", RetrievalFilters())
    assert ids["searchable"] not in context.eligible_version_ids
    app.run()
    assert (
        len(
            rows(
                tmp_path,
                "SELECT id FROM review_events WHERE version_id=? AND action='revoke'",
                ids["searchable"],
            )
        )
        == 1
    )


def test_empty_knowledge_base(tmp_path):
    app = kb_app(tmp_path)
    assert any("empty" in i.value for i in app.info)


def test_refresh_is_noop_or_creates_pending_update(tmp_path):
    seed, ids = seeded(tmp_path)
    # The kb page builds its own container; give its snapshot service the same fetcher.
    setup_body = "<main><p>Grid connection text for searchable.</p></main>"
    script_setup = (
        "import hashlib\n"
        "from gridlens.contracts import FetchedDocument\n"
        "class F:\n"
        "    def fetch(self, url):\n"
        "        body = st.session_state.get('body', '').encode()\n"
        "        return FetchedDocument(requested_url=url, final_url=url,\n"
        "            content_type='text/html', body=body,\n"
        "            raw_sha256=hashlib.sha256(body).hexdigest(),\n"
        "            fetched_at='2026-10-12T00:00:00+00:00', redirect_count=0)\n"
        "c.snapshots.fetcher = F()\n"
    )
    script = (
        "from pathlib import Path\n"
        "import streamlit as st\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        "from gridlens.ui.knowledge_base import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        f"st.session_state.setdefault('kb_version_id', {ids['searchable']!r})\n"
        f"st.session_state.setdefault('body', {setup_body!r})\n" + script_setup + "render(c)\n"
    )
    app = AppTest.from_string(script).run()
    button(app, "Refresh from source").click().run()
    assert any("unchanged" in s.value for s in app.success)
    count = len(rows(tmp_path, "SELECT id FROM document_versions"))

    app.session_state["body"] = "<main><p>Grid connection text, revised.</p></main>"
    button(app, "Refresh from source").click().run()
    assert any("waiting for review" in w.value for w in app.warning)
    assert len(rows(tmp_path, "SELECT id FROM document_versions")) == count + 1
    statuses = [
        r["Status"] for r in app.dataframe[0].value.to_dict("records") if r["Title"] == "searchable"
    ]
    assert "Searchable · update awaiting review" in statuses
