"""Live-mode indexing with the real prepared model and Chroma. Run with `-m local_model`."""

import hashlib

import pytest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import FetchedDocument, SearchHitDTO
from gridlens.documents.snapshots import SnapshotService
from gridlens.errors import AppError
from gridlens.providers.local_embeddings import read_manifest

BODY = (
    b"<main><h1>Synthetic connection guide</h1>"
    b"<p>A data centre applicant must submit a load forecast before connection studies.</p>"
    b"<h2>Costs</h2><p>The bakery menu lists sourdough and croissants.</p></main>"
)


class Fetcher:
    def fetch(self, url):
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            content_type="text/html",
            body=BODY,
            raw_sha256=hashlib.sha256(BODY).hexdigest(),
            fetched_at="2026-10-11T00:00:00+00:00",
            redirect_count=0,
        )


@pytest.mark.local_model
def test_live_ingestion_publishes_and_whitelist_search_finds_it(tmp_path):
    prepared = Settings.from_env()
    try:
        read_manifest(prepared)
    except AppError:
        pytest.skip("Local model is not prepared; a skip is not a successful model check")
    settings = Settings(
        project_root=tmp_path / "app",
        mode="live",
        auth_dir=tmp_path / "auth",
        local_model_dir=prepared.local_model_dir,
    )
    app = build_container(settings)
    assert app.ingestion is not None
    source_id = app.sources.save_candidate(
        SearchHitDTO(
            title="Synthetic guide",
            url="https://synthetic.example/g",
            snippet="s",
            provider_rank=1,
            jurisdiction="NZ",
        ),
        "https://synthetic.example/g",
    )
    preview = SnapshotService(
        app.db, app.sources, Fetcher(), settings.data_dir, max_pdf_pages=5, pdf_timeout_seconds=5
    ).capture(source_id)
    app.review.approve(preview.version_id, preview.snapshot_sha256, "Researcher")
    result = app.ingestion.ingest(preview.version_id, "smoke-1")
    assert result.status == "completed", result.error_code
    eligible = [v["id"] for v in app.research.eligible_versions(app.ingestion.fingerprint)]
    assert eligible == [preview.version_id]

    query = app.embeddings.embed(["What must a data centre submit before studies?"], "query")
    hits = app.vectors.query(query.vectors[0], eligible, 5)
    assert hits and len(hits) == result.indexed_chunks
    assert app.vectors.query(query.vectors[0], [], 5) == []
    print(f"chunks={result.indexed_chunks} top_distance={hits[0].distance:.3f}")
