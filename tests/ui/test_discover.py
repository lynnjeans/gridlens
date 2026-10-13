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
    assert any("Search results" in item.value for item in app.subheader)
    assert any("Synthetic connection guide" in item.value for item in app.markdown)
    assert any("1 search call" in item.value for item in app.caption)
    button(app, "Select for review").click().run()
    assert any("Review queue" in item.value for item in app.success)

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
    assert any("Review queue" in item.value for item in app.success)
    assert any("pending lead" in item.value for item in app.success)


def test_empty_partial_and_failed_states_are_distinct():
    script = """
from gridlens.contracts import SearchRunDetail
from gridlens.ui.discover import _show_results

base = dict(run_id="r", operation_key="o", topic="topic", queries=["topic"],
            calls_used=1, candidates=[], error_codes=[], mode="fixture")
_show_results(None, SearchRunDetail(**base, status="completed"))
_show_results(None, SearchRunDetail(**(base | {"run_id": "p", "operation_key": "p",
    "status": "partial", "error_codes": ["RATE_LIMITED"]})))
_show_results(None, SearchRunDetail(**(base | {"run_id": "f", "operation_key": "f",
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
        "c.sources.queue_for_review(lead.source_id)\n"
        "render(c)\n"
    )
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert app.radio[0].value == "capture"
    assert "To extract (1)" in app.radio[0].options[0]
    assert any("example.org" in item.value for item in app.markdown)


def test_every_selected_candidate_waits_in_the_persistent_review_queue(tmp_path):
    script = (
        "from pathlib import Path\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        "from gridlens.ui.review import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        "render(c)\n"
    )
    from pathlib import Path

    from gridlens.bootstrap import build_container
    from gridlens.config import Settings

    c = build_container(Settings(project_root=Path(tmp_path)))
    first = c.discovery.add_source("https://synthetic.example/connection-guide")
    second = c.discovery.add_source("https://example.org/second")
    for source_id in (first.source_id, second.source_id, first.source_id):
        c.sources.queue_for_review(source_id)

    # A fresh session (e.g. a browser reload) still shows both selections in order.
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert app.radio[0].value == "capture"
    assert "To extract (2)" in app.radio[0].options[0]
    assert [item.value for item in app.caption if item.value.startswith("https://")] == [
        "https://synthetic.example/connection-guide",
        "https://example.org/second",
    ]

    next(b for b in app.button if b.key == f"dequeue-{second.source_id}").click().run()
    assert not app.exception
    assert any("Removed from the Review queue" in item.value for item in app.info)
    assert [s["id"] for s in c.sources.review_queue()] == [first.source_id]

    next(b for b in app.button if b.key == f"capture-{first.source_id}").click().run()
    assert not app.exception
    assert c.sources.review_queue() == []
    # Extraction stays in step 1; the document waits, preselected, in step 2.
    assert app.radio[0].value == "capture"
    assert any("Text extracted" in item.value for item in app.success)
    assert "To review (1)" in app.radio[0].options[1]
    app.radio[0].set_value("review").run()
    assert any(item.label == "Approve" for item in app.button)
