from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from gridlens.config import PROJECT_ROOT


@pytest.mark.parametrize(
    "module,title",
    [
        ("discover", "Discover"),
        ("review", "Review"),
        ("knowledge_base", "Knowledge Base"),
        ("ask", "Ask & Gaps"),
    ],
)
def test_each_page_boots_without_credentials(tmp_path, module, title):
    script = (
        "from pathlib import Path\n"
        "from gridlens.config import Settings\n"
        "from gridlens.bootstrap import build_container\n"
        f"from gridlens.ui.{module} import render\n"
        f"c=build_container(Settings(project_root=Path({str(tmp_path)!r})))\n"
        "render(c)\n"
    )
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert app.title[0].value == title
    app.run()
    assert not app.exception


def test_entrypoint_navigation_rerun_does_not_call_providers(tmp_path, monkeypatch):
    # Point the app at a temporary root without changing authoritative code or .env.
    import gridlens.config as config
    from gridlens.providers.fakes import FakeAnswerProvider, FakeSearchProvider

    original = config.Settings.from_env.__func__
    monkeypatch.setattr(
        config.Settings,
        "from_env",
        classmethod(lambda cls: original(cls, Path(tmp_path), {"APP_MODE": "fixture"})),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("UI rerun must not make a provider call")

    monkeypatch.setattr(FakeSearchProvider, "search", forbidden)
    monkeypatch.setattr(FakeAnswerProvider, "generate", forbidden)
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run()
    assert not app.exception
    assert app.main.title[0].value == "Discover"
    app.run()
    assert not app.exception
    assert not (tmp_path / "data/fixture/auth").exists()


def test_spawned_worker_import_does_not_run_the_app(monkeypatch):
    # PDF extraction uses a spawn worker, which re-imports the main script as __mp_main__.
    import runpy

    import streamlit

    import gridlens.bootstrap

    def forbidden(*args, **kwargs):
        raise AssertionError("worker import must not build the app or render pages")

    monkeypatch.setattr(gridlens.bootstrap, "build_container", forbidden)
    monkeypatch.setattr(streamlit, "set_page_config", forbidden)
    namespace = runpy.run_path(str(PROJECT_ROOT / "app.py"), run_name="__mp_main__")
    assert callable(namespace["main"])
