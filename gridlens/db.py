"""Short-lived SQLite connections and forward-only, atomic initialization."""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

# Forward-only, applied in order; never edit a shipped migration.
MIGRATIONS = ("001_initial.sql", "002_chunk_segments.sql")


def now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                exists = c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                versions = (
                    {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
                    if (exists)
                    else set()
                )
                if any(v > len(MIGRATIONS) for v in versions):
                    raise RuntimeError("Database schema is newer than this application")
                for version, name in enumerate(MIGRATIONS, start=1):
                    if version in versions:
                        continue
                    migration = files("gridlens").joinpath(f"migrations/{name}").read_text()
                    # executescript commits implicitly, so execute statements individually.
                    statement = ""
                    for line in migration.splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            c.execute(statement)
                            statement = ""
                    c.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, now()))
                c.commit()
            except BaseException:
                c.rollback()
                raise
