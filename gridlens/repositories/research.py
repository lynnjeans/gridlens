import json

from gridlens.db import Database


class ResearchRepository:
    def __init__(self, db: Database):
        self.db = db

    def list_versions(self) -> list[dict]:
        with self.db.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT v.*, s.title FROM document_versions v "
                    "JOIN sources s ON s.id=v.source_id "
                    "ORDER BY v.created_at DESC"
                )
            ]

    def review_events(self, version_id: str) -> list[dict]:
        with self.db.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM review_events WHERE version_id=? ORDER BY created_at, rowid",
                    (version_id,),
                )
            ]

    def eligible_versions(self, fingerprint: str, jurisdiction: str | None = "NZ") -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT * FROM document_versions WHERE review_status='approved' "
                "AND ingestion_status='ready' AND version_status='active' "
                "AND approved_snapshot_sha256=snapshot_sha256 AND index_fingerprint=?",
                (fingerprint,),
            )
            return [
                dict(r)
                for r in rows
                if jurisdiction is None
                or (json.loads(r["metadata_json"]).get("jurisdiction") in {jurisdiction, "GLOBAL"})
            ]
