from streamlit.testing.v1 import AppTest


def discover_app(tmp_path, mode="fixture"):
    script = (
        "from pathlib import Path\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        "from gridlens.ui.discover import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r}), mode={mode!r}))\n"
        "render(c)\n"
    )
    return AppTest.from_string(script).run()


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_fixture_search_renders_candidate_and_rerun_is_idempotent(tmp_path):
    app = discover_app(tmp_path)
    app.text_input[0].set_value("New Zealand grid connection")
    button(app, "Search sources").click().run()
    assert not app.exception
    assert any("Synthetic connection guide" in item.value for item in app.subheader)
    assert any("1 search call" in item.value for item in app.caption)
    button(app, "Select for review").click().run()
    assert app.session_state["selected_source_id"]

    app.run()
    assert not app.exception
    with __import__("sqlite3").connect(tmp_path / "data/fixture/research.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0] == 1


def test_input_error_and_missing_live_key_are_distinct(tmp_path):
    app = discover_app(tmp_path)
    app.text_input[0].set_value("x")
    button(app, "Search sources").click().run()
    assert any("between 3 and 500" in item.value for item in app.error)

    live = discover_app(tmp_path / "live", mode="live")
    assert button(live, "Search sources").disabled
    assert any("SEARCH_PROVIDER" in item.value for item in live.info)


def test_manual_source_is_saved_and_selected_for_review(tmp_path):
    app = discover_app(tmp_path)
    app.text_input[1].set_value("https://example.org/public-guide")
    button(app, "Add for review").click().run()
    assert not app.exception
    assert app.session_state["selected_source_id"]
    assert any("pending lead" in item.value for item in app.success)


def test_empty_partial_and_failed_states_are_distinct():
    script = """
from gridlens.contracts import SearchRunDetail
from gridlens.ui.discover import _show_results

base = dict(run_id="r", operation_key="o", topic="topic", queries=["topic"],
            calls_used=1, candidates=[], error_codes=[], mode="fixture")
_show_results(SearchRunDetail(**base, status="completed"))
_show_results(SearchRunDetail(**(base | {"run_id": "p", "operation_key": "p",
    "status": "partial", "error_codes": ["RATE_LIMITED"]})))
_show_results(SearchRunDetail(**(base | {"run_id": "f", "operation_key": "f",
    "status": "failed", "error_codes": ["PROVIDER_TIMEOUT"]})))
"""
    app = AppTest.from_string(script).run()
    assert any("No candidates" in item.value for item in app.info)
    assert any("Some searches failed" in item.value for item in app.warning)
    assert any("Search failed" in item.value for item in app.error)


def test_review_page_displays_selected_pending_lead(tmp_path):
    script = (
        "from pathlib import Path\n"
        "import streamlit as st\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        "from gridlens.ui.review import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        "lead=c.discovery.add_source('https://example.org/public-guide')\n"
        "st.session_state['selected_source_id']=lead.source_id\n"
        "render(c)\n"
    )
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert any(item.value == "Selected source" for item in app.subheader)
    assert any("example.org" in item.value for item in app.markdown)
