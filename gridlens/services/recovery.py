"""Startup recovery: only runs whose owner process has exited are marked interrupted.

Approved sources, versions and answers are never touched; nothing is deleted or retried.
"""

import json

from gridlens.contracts import DTO
from gridlens.db import Database, now
from gridlens.runlocks import RunLocks


class RecoveryReport(DTO):
    interrupted_ingestions: list[str]
    interrupted_searches: list[str]
    still_running: int


class RecoveryService:
    def __init__(self, db: Database, locks: RunLocks):
        self.db = db
        self.locks = locks

    def recover(self) -> RecoveryReport:
        ingestions, searches, active = [], [], 0
        with self.db.connect() as c:
            runs = [
                dict(r)
                for r in c.execute(
                    "SELECT id, version_id FROM ingestion_runs WHERE status='processing'"
                )
            ]
            pending_searches = [
                dict(r)
                for r in c.execute(
                    "SELECT id, filters_json FROM search_runs WHERE status='running'"
                )
            ]
        for run in runs:
            if not self.locks.is_abandoned(f"ingest-{run['id']}"):
                active += 1
                continue
            with self.db.transaction() as c:
                changed = c.execute(
                    "UPDATE ingestion_runs SET status='failed', "
                    "error_code='INGESTION_INTERRUPTED', finished_at=? "
                    "WHERE id=? AND status='processing'",
                    (now(), run["id"]),
                ).rowcount
                if changed:
                    # The version can be retried; it was never Ready, so nothing is exposed.
                    c.execute(
                        "UPDATE document_versions SET ingestion_status='failed' "
                        "WHERE id=? AND ingestion_status='processing'",
                        (run["version_id"],),
                    )
                    ingestions.append(run["id"])
        for run in pending_searches:
            if not self.locks.is_abandoned(f"search-{run['id']}"):
                active += 1
                continue
            filters = json.loads(run["filters_json"])
            filters["error_codes"] = [*filters.get("error_codes", []), "SEARCH_INTERRUPTED"]
            with self.db.transaction() as c:
                if c.execute(
                    "UPDATE search_runs SET status='failed', error_code='SEARCH_INTERRUPTED', "
                    "filters_json=?, finished_at=? WHERE id=? AND status='running'",
                    (json.dumps(filters), now(), run["id"]),
                ).rowcount:
                    searches.append(run["id"])
        return RecoveryReport(
            interrupted_ingestions=ingestions, interrupted_searches=searches, still_running=active
        )
