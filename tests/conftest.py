from pathlib import Path

import pytest

from gridlens.config import Settings
from gridlens.db import Database


@pytest.fixture
def settings(tmp_path):
    return Settings(project_root=tmp_path)


@pytest.fixture
def db(settings):
    database = Database(settings.data_dir / "research.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"
