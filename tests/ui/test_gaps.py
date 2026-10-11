import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.contracts import RetrievalFilters
from gridlens.providers.fakes import FakeAnswerProvider, FakeSearchProvider


@pytest.fixture
def search_calls(monkeypatch):
    calls = []
    original = FakeSearchProvider.search

    def counted(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FakeSearchProvider, "search", counted)
    return calls


def seed_gap(tmp_path, question="Which studies does a 50 MW load need?", key="op-1"):
    app = build_container(Settings(project_root=Path(tmp_path)))
    app.answer_service.ask(question, RetrievalFilters(), key, FakeAnswerProvider())
    return app


def page(tmp_path, module="ask", setup=""):
    script = (
        "from pathlib import Path\n"
        "import streamlit as st\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        f"from gridlens.ui.{module} import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        f"{setup}"
        "render(c)\n"
    )
    return AppTest.from_string(script).run()


def gaps_rows(tmp_path):
    with sqlite3.connect(tmp_path / "data/fixture/research.sqlite3") as c:
        return c.execute(
            "SELECT status, resolution_note, reason_type FROM knowledge_gaps"
        ).fetchall()


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_empty_gap_list(tmp_path):
    app = page(tmp_path)
    assert any("No knowledge gaps here" in i.value for i in app.info)


def test_gap_detail_and_suggested_query_prefill_without_search(tmp_path, search_calls):
    seed_gap(tmp_path)
    app = page(tmp_path)
    assert not app.exception
    assert any("No approved source covers this yet" in m.value for m in app.markdown)
    assert any("region NZ" in c.value for c in app.caption)
    text = " ".join(m.value for m in app.markdown)
    assert "industry" not in text.lower() and "no research" not in text.lower()
    button(app, "Use in Discover").click().run()
    assert app.session_state["discover_prefill"] == "Which studies does a 50 MW load need?"
    assert search_calls == []

    discover = page(
        tmp_path,
        "discover",
        "st.session_state['discover_prefill']='Which studies does a 50 MW load need?'\n",
    )
    assert discover.text_input(key="discover_topic").value == (
        "Which studies does a 50 MW load need?"
    )
    assert any("Review it, then search" in i.value for i in discover.info)
    discover.run()
    assert search_calls == []  # still nothing until the user clicks Search


def test_repeated_question_shows_the_same_open_gap(tmp_path):
    app = seed_gap(tmp_path)
    app.answer_service.ask(
        "which studies does a 50 MW load need?", RetrievalFilters(), "op-2", FakeAnswerProvider()
    )
    ui = page(tmp_path)
    assert len(ui.selectbox(key="gap_pick_Open").options) == 1


def test_edit_resolve_dismiss_and_reopen(tmp_path):
    seed_gap(tmp_path)
    seed_gap(tmp_path, question="Who approves a connection offer?", key="op-2")
    app = page(tmp_path)
    gap_id = app.selectbox(key="gap_pick_Open").value
    app.selectbox(key=f"gap-reason-{gap_id}").set_value("needs_external_validation")
    button(app, "Save changes").click().run()
    assert not app.exception
    assert any("Gap updated" in s.value for s in app.success)
    assert ("open", None, "needs_external_validation") in gaps_rows(tmp_path)

    button(app, "Mark resolved").click().run()
    assert any("Add a note" in e.value for e in app.error)
    app.text_input(key=f"gap-note-{gap_id}").set_value("Approved the official guide.")
    button(app, "Mark resolved").click().run()
    assert ("resolved", "Approved the official guide.", "needs_external_validation") in gaps_rows(
        tmp_path
    )

    other = app.selectbox(key="gap_pick_Open").value
    assert other != gap_id
    button(app, "Dismiss").click().run()
    assert sorted(r[0] for r in gaps_rows(tmp_path)) == ["dismissed", "resolved"]

    app.radio(key="gap_status").set_value("Dismissed").run()
    button(app, "Reopen").click().run()
    assert sorted(r[0] for r in gaps_rows(tmp_path)) == ["open", "resolved"]
