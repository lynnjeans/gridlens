import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from gridlens.bootstrap import build_container
from gridlens.cli import doctor
from gridlens.config import Settings
from gridlens.contracts import DiscoveryRequest, MetadataCorrection, RetrievalFilters
from gridlens.errors import AppError
from gridlens.oplog import RedactingFilter, redact
from gridlens.providers.fakes import FakeAnswerProvider, FakeSearchProvider

GUIDE = "https://synthetic.example/connection-guide"


@pytest.fixture
def app(tmp_path):
    return build_container(Settings(project_root=Path(tmp_path)))


def approved_version(app):
    source = app.discovery.add_source(GUIDE)
    preview = app.snapshots.capture(source.source_id)
    current = app.review.update_metadata(
        preview.version_id,
        preview.snapshot_sha256,
        MetadataCorrection(title="Guide", jurisdiction="NZ", source_type="technical"),
    ).snapshot_sha256
    app.review.approve(preview.version_id, current, "Researcher")
    return preview.version_id


def crash_mid_ingestion(app, version_id, run_id="run-crashed"):
    """What a killed process leaves behind: a processing run and no lock holder."""
    with app.db.transaction() as c:
        c.execute(
            "INSERT INTO ingestion_runs VALUES (?,?,?,'embedding','processing',1,5,2,"
            "'2026-10-12T00:00:00+00:00',NULL,NULL)",
            (run_id, f"op-{run_id}", version_id),
        )
        c.execute(
            "UPDATE document_versions SET ingestion_status='processing' WHERE id=?", (version_id,)
        )


def test_crashed_ingestion_is_marked_interrupted_and_can_be_retried(app):
    version = approved_version(app)
    crash_mid_ingestion(app, version)
    with pytest.raises(AppError) as raised:
        app.ingestion.ingest(version, "op-retry-too-early")
    assert raised.value.code == "INGESTION_IN_PROGRESS"
    report = app.recovery.recover()
    assert report.interrupted_ingestions == ["run-crashed"] and report.still_running == 0
    row = app.sources.get_version(version)
    assert (row["ingestion_status"], row["version_status"]) == ("failed", "candidate")
    with app.db.connect() as c:
        run = c.execute(
            "SELECT status, error_code FROM ingestion_runs WHERE id='run-crashed'"
        ).fetchone()
    assert tuple(run) == ("failed", "INGESTION_INTERRUPTED")
    assert app.ingestion.ingest(version, "op-retry").status == "completed"
    assert app.recovery.recover().interrupted_ingestions == []  # idempotent


def test_a_live_owner_is_never_reclaimed(app, tmp_path):
    version = approved_version(app)
    crash_mid_ingestion(app, version, "run-live")
    lock_dir = app.settings.data_dir / "locks"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path; from gridlens.runlocks import RunLocks;\n"
            "locks = RunLocks(Path(sys.argv[1]))\n"
            "with locks.hold('ingest-run-live'):\n"
            "    print('held', flush=True); time.sleep(30)\n",
            str(lock_dir),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        report = app.recovery.recover()
        assert report.still_running == 1 and report.interrupted_ingestions == []
        assert app.sources.get_version(version)["ingestion_status"] == "processing"
    finally:
        holder.kill()
        holder.wait()
    assert app.recovery.recover().interrupted_ingestions == ["run-live"]


def test_interrupted_search_run_is_closed_and_search_continues(app):
    with app.db.transaction() as c:
        c.execute(
            "INSERT INTO search_runs VALUES ('search-crashed','op-s','topic','{}','[\"topic\"]',"
            "'fixture','running',0,'2026-10-12T00:00:00+00:00',NULL,NULL)"
        )
    report = app.recovery.recover()
    assert report.interrupted_searches == ["search-crashed"]
    with app.db.connect() as c:
        row = c.execute(
            "SELECT status, error_code, filters_json FROM search_runs WHERE id='search-crashed'"
        ).fetchone()
    assert (row[0], row[1]) == ("failed", "SEARCH_INTERRUPTED")
    assert "SEARCH_INTERRUPTED" in json.loads(row[2])["error_codes"]
    result = app.discovery.discover(DiscoveryRequest(topic="grid connection"), "op-new")
    assert result.status == "completed"


def test_valid_data_survives_restart_and_recovery(app, tmp_path):
    version = approved_version(app)
    app.ingestion.ingest(version, "op-1")
    qa = app.answer_service.ask(
        "How does the synthetic process start?", RetrievalFilters(), "q-1", FakeAnswerProvider()
    )
    restarted = build_container(Settings(project_root=Path(tmp_path)))
    restarted.recovery.recover()
    eligible = restarted.research.eligible_versions(restarted.ingestion.fingerprint, None)
    assert [v["id"] for v in eligible] == [version]
    assert restarted.answer_service.replay("q-1") == qa


def test_rate_limit_chains_stay_within_budget(app):
    version = approved_version(app)
    app.ingestion.ingest(version, "op-1")
    provider = FakeAnswerProvider("RATE_LIMITED")
    failed = app.answer_service.ask("How does it start?", RetrievalFilters(), "q-429", provider)
    assert failed.error == {"code": "RATE_LIMITED"} and provider.calls == 1
    search = FakeSearchProvider("RATE_LIMITED")
    app.discovery.provider = search
    result = app.discovery.discover(DiscoveryRequest(topic="data centre grid connection"), "op-429")
    assert result.status == "failed" and search.calls <= 3
    assert (
        app.discovery.discover(DiscoveryRequest(topic="data centre grid connection"), "op-429")
        == result
    )
    assert search.calls <= 3  # replaying the operation makes no new calls


def test_operation_log_is_redacted_and_text_free(app):
    version = approved_version(app)
    app.ingestion.ingest(version, "op-1")
    app.answer_service.ask(
        "SECRET QUESTION TEXT about grid?", RetrievalFilters(), "q-1", FakeAnswerProvider()
    )
    log = (app.settings.data_dir / "logs" / "operations.jsonl").read_text()
    entries = [json.loads(line) for line in log.splitlines()]
    assert {e["kind"] for e in entries} == {"ingest", "answer"}
    assert {e["usage_category"] for e in entries} == {"local_inference", "fixture"}
    assert "SECRET QUESTION TEXT" not in log and "synthetic process" not in log.lower()


def test_redaction_patterns_and_logging_filter(caplog):
    samples = {
        "Authorization: Bearer abc.def": "abc.def",
        "https://auth.openai.com/authorize?code=CODE123&state=STATE9": "CODE123",
        "id_token_hint=eyJhbGciOi.eyJzdWIiOi.sig": "eyJhbGciOi",
        '{"refresh_token": "r-secret-1"}': "r-secret-1",
        "key tvly-abc123def": "tvly-abc123def",
        "GET https://serpapi.com/search?engine=google&api_key=SERP123&q=x": "SERP123",
    }
    for text, secret in samples.items():
        assert secret not in redact(text)
    logger = logging.getLogger("gridlens.test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="gridlens.test"):
        logger.info("callback %s", "http://127.0.0.1:1455/auth/callback?code=LEAK&state=s")
    assert "LEAK" not in caplog.text


def test_doctor_is_offline_and_secret_free(tmp_path):
    settings = Settings(project_root=Path(tmp_path), tavily_api_key=SecretStr("tvly-doctor-secret"))
    build_container(settings)
    report = doctor(settings)
    dumped = json.dumps(report)
    assert "tvly-doctor-secret" not in dumped
    assert report["search_key_configured"] is True
    assert report["search_provider"] == "tavily"
    assert report["database"]["schema_current"] is True
    assert report["data_dir_writable"] is True
