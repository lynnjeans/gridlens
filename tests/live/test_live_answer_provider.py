"""Real ChatGPT plan-usage answer smoke with synthetic evidence (uses plan usage).

    APP_MODE=live GRIDLENS_LIVE_ANSWER=1 .venv/bin/python -m pytest -m live -k live_answer -s

Requires a signed-in account selected in GridLens (`gridlens login`). Optional
GRIDLENS_LIVE_MODEL=<slug> picks a model from that account's catalog; otherwise the first
listed model is used. Prints only slug, output mode, terminal event and usage.
"""

import os

import pytest

from gridlens.auth.catalog import ModelCatalog
from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.sessions import SessionManager
from gridlens.config import Settings
from gridlens.contracts import ChunkDTO, Locator, RetrievalContext
from gridlens.providers.chatgpt_oauth import ChatGPTAnswerProvider

SYNTHETIC = (
    "Synthetic guide (not a real policy): an applicant submits a load forecast before "
    "connection studies begin."
)


@pytest.mark.live
@pytest.mark.enable_socket
def test_real_answer_with_synthetic_evidence():
    if os.environ.get("GRIDLENS_LIVE_ANSWER") != "1":
        pytest.skip("Set GRIDLENS_LIVE_ANSWER=1 to spend plan usage on a real answer smoke")
    settings = Settings.from_env()
    if settings.mode != "live":
        pytest.skip("Real answers require APP_MODE=live")
    sessions = SessionManager(FileCredentialStore(settings.auth_dir))
    handle = sessions.current()
    if handle is None:
        pytest.skip("Select a signed-in account first")
    models = ModelCatalog(sessions).fetch(handle)
    slugs = [m.slug for m in models]
    slug = os.environ.get("GRIDLENS_LIVE_MODEL") or (slugs[0] if slugs else "")
    assert slug in slugs, "the chosen model must come from this account's catalog"
    chunk = ChunkDTO(
        chunk_id="synthetic-1",
        version_id="synthetic",
        ordinal=0,
        text=SYNTHETIC,
        text_sha256="0" * 64,
        embedding_text=SYNTHETIC,
        token_count=30,
        source_segment_ids=["html-0001"],
        locator=Locator(kind="html", paragraph_index=1),
        index_fingerprint="f" * 64,
    )
    context = RetrievalContext(
        chunks=[chunk],
        eligible_version_ids=["synthetic"],
        filters={"region": "NZ"},
        index_fingerprint="f" * 64,
    )
    provider = ChatGPTAnswerProvider(sessions, handle, slug)
    draft = provider.generate("What does an applicant submit before studies?", context)
    record = provider.last
    print(
        f"slug={slug} model={record.model} output_mode={record.output_mode} "
        f"terminal={record.terminal_event} status={draft.evidence_status} usage={record.usage}"
    )
    assert record.terminal_event == "response.completed"
