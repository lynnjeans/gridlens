import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import MetadataCorrection
from gridlens.providers.fakes import FakeAnswerProvider

GUIDE = "https://synthetic.example/connection-guide"


def publish(tmp_path):
    app = build_container(Settings(project_root=Path(tmp_path)))
    source = app.discovery.add_source(GUIDE)
    preview = app.snapshots.capture(source.source_id)
    # A reviewer labels the manually added source before approving it.
    corrected = app.review.update_metadata(
        preview.version_id,
        preview.snapshot_sha256,
        MetadataCorrection(
            title=preview.metadata["title"], jurisdiction="NZ", source_type="technical"
        ),
    )
    app.review.approve(preview.version_id, corrected.snapshot_sha256, "Researcher")
    assert app.ingestion.ingest(preview.version_id, "seed").status == "completed"
    return app, preview.version_id


def ask_app(tmp_path, setup=""):
    script = (
        "from pathlib import Path\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        "from gridlens.ui.ask import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        f"{setup}"
        "render(c)\n"
    )
    return AppTest.from_string(script).run()


def submit(app, question="How does the synthetic process start?", region=None):
    app.text_area(key="ask_question").set_value(question)
    if region:
        app.selectbox(key="ask_region").set_value(region)
    next(b for b in app.button if b.label == "Ask GridLens").click().run()
    assert not app.exception
    return app


def rows(tmp_path, sql):
    with sqlite3.connect(tmp_path / "data/fixture/research.sqlite3") as c:
        return c.execute(sql).fetchall()


def test_partial_answer_maps_claims_to_citations(tmp_path, monkeypatch):
    publish(tmp_path)
    calls = []
    original = FakeAnswerProvider.generate

    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FakeAnswerProvider, "generate", counted)
    app = submit(ask_app(tmp_path))
    assert any("Partly answered" in w.value for w in app.warning)
    assert any(m.value.startswith("**Fact:**") and m.value.endswith("[1]") for m in app.markdown)
    [expander] = [e for e in app.expander if e.label.startswith("[1] ")]
    assert expander.label == "[1] synthetic.example"  # reviewed snapshot title
    assert any("paragraph" in c.value for c in expander.caption)
    assert any("Supports claim(s): c1" in c.value for c in expander.caption)
    assert any(m.value.startswith("> ") for m in expander.markdown)
    assert any("Missing evidence" in m.value for m in app.markdown)
    assert any("Synthetic development answer" in c.value for c in app.caption)
    app.run()
    app.run()
    assert len(calls) == 1  # reruns render the stored answer, never re-ask
    assert len(rows(tmp_path, "SELECT id FROM qa_records")) == 1


def test_answered_path(tmp_path):
    app_container, version = publish(tmp_path)
    setup = (
        "from gridlens.contracts import AnswerDraft\n"
        "class Answered:\n"
        "    def generate(self, question, context, repair=None):\n"
        "        chunk = context.chunks[0]\n"
        "        return AnswerDraft.model_validate({'evidence_status': 'answered', 'claims': [\n"
        "            {'claim_id': 'c1', 'kind': 'inference',\n"
        "             'text': 'An application comes first.',\n"
        "             'evidence': [{'chunk_id': chunk.chunk_id,\n"
        "                           'support_quote': chunk.text[:40]}]}],\n"
        "            'limitations': [], 'missing_evidence': []})\n"
        "c.answers = Answered()\n"
    )
    app = submit(ask_app(tmp_path, setup))
    assert any("Answered from approved sources" in s.value for s in app.success)
    assert any(m.value.startswith("**Inference:**") for m in app.markdown)


def test_insufficient_when_nothing_is_approved(tmp_path):
    app = submit(ask_app(tmp_path))
    assert any("Insufficient evidence" in i.value for i in app.info)
    assert not app.error
    assert rows(tmp_path, "SELECT execution_status, evidence_status FROM qa_records") == [
        ("completed", "insufficient")
    ]


def test_provider_failure_is_shown_as_failure_not_insufficient(tmp_path):
    publish(tmp_path)
    setup = (
        "from gridlens.providers.fakes import FakeAnswerProvider\n"
        "c.answers = FakeAnswerProvider('USAGE_LIMITED')\n"
    )
    app = submit(ask_app(tmp_path, setup))
    assert any("usage limit" in e.value for e in app.error)
    assert not any("Insufficient" in i.value for i in app.info)
    assert any(b.label == "View ChatGPT usage" for b in app.get("link_button"))


def test_history_rechecks_source_status(tmp_path):
    app_container, version = publish(tmp_path)
    app = submit(ask_app(tmp_path))
    app_container.review.revoke(version, "Researcher", "Withdrawn")
    app.run()
    assert any("approval was revoked" in w.value for w in app.warning)


def test_input_validation(tmp_path):
    app = submit(ask_app(tmp_path), question="x")
    assert any("between 3 and 2000" in e.value for e in app.error)
    assert rows(tmp_path, "SELECT id FROM qa_records") == []
