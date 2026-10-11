import json
from uuid import uuid4

from gridlens.contracts import SearchCandidate, SearchHitDTO, SearchRunDetail
from gridlens.db import Database, now


class SourceRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_candidate(
        self, hit: SearchHitDTO, canonical_url: str, *, topic: str | None = None
    ) -> str:
        with self.db.transaction() as c:
            return self.save_candidate_with_connection(c, hit, canonical_url, topic=topic)

    def save_candidate_with_connection(
        self, connection, hit: SearchHitDTO, canonical_url: str, *, topic: str | None = None
    ) -> str:
        row = connection.execute(
            "SELECT id, topics_json FROM sources WHERE canonical_url=?", (canonical_url,)
        ).fetchone()
        if row:
            if topic:
                topics = json.loads(row["topics_json"])
                if topic not in topics:
                    topics.append(topic)
                    connection.execute(
                        "UPDATE sources SET topics_json=? WHERE id=?",
                        (json.dumps(topics, ensure_ascii=False), row["id"]),
                    )
            return row["id"]
        source_id = str(uuid4())
        connection.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                canonical_url,
                hit.url,
                hit.title,
                hit.publisher,
                hit.source_type,
                hit.jurisdiction,
                json.dumps([topic] if topic else [], ensure_ascii=False),
                "unknown",
                now(),
            ),
        )
        return source_id

    def get_search_run(self, operation_key: str, mode: str) -> SearchRunDetail | None:
        with self.db.connect() as c:
            run = c.execute(
                "SELECT * FROM search_runs WHERE operation_key=?", (operation_key,)
            ).fetchone()
            if not run or run["status"] == "running":
                return None
            hits = c.execute(
                "SELECT h.*, s.title, s.original_url, s.publisher, s.source_type, "
                "s.jurisdiction FROM search_hits h JOIN sources s ON s.id=h.source_id "
                "WHERE h.search_run_id=? ORDER BY h.rank, h.source_id",
                (run["id"],),
            ).fetchall()
            metadata = json.loads(run["filters_json"])
            return SearchRunDetail(
                run_id=run["id"],
                operation_key=run["operation_key"],
                topic=run["topic"],
                queries=json.loads(run["queries_json"]),
                status=run["status"],
                calls_used=run["calls_used"],
                error_codes=metadata.get("error_codes", []),
                candidates=[
                    SearchCandidate(
                        source_id=h["source_id"],
                        title=h["title"],
                        url=h["original_url"],
                        snippet=h["snippet"],
                        publisher=h["publisher"],
                        published_at=json.loads(h["metadata_json"]).get("published_at"),
                        source_type=h["source_type"],
                        jurisdiction=h["jurisdiction"],
                        relevance_reason=h["relevance_reason"],
                        provider_rank=h["rank"],
                    )
                    for h in hits
                ],
                mode=mode,
            )

    def list_sources(self) -> list[dict]:
        with self.db.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM sources ORDER BY created_at DESC")]

    def get_source(self, source_id: str) -> dict | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            return dict(row) if row else None

    def get_version_by_snapshot(self, source_id: str, snapshot_sha256: str) -> dict | None:
        with self.db.connect() as c:
            row = c.execute(
                "SELECT * FROM document_versions WHERE source_id=? AND snapshot_sha256=?",
                (source_id, snapshot_sha256),
            ).fetchone()
            return dict(row) if row else None

    def mark_access(self, source_id: str, status: str) -> None:
        with self.db.transaction() as c:
            changed = c.execute(
                "UPDATE sources SET access_status=? WHERE id=?", (status, source_id)
            ).rowcount
            if changed != 1:
                raise ValueError("Unknown source")

    def latest_published_at(self, source_id: str) -> str | None:
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT metadata_json FROM search_hits WHERE source_id=? ORDER BY rowid DESC",
                (source_id,),
            )
            for row in rows:
                value = json.loads(row["metadata_json"]).get("published_at")
                if isinstance(value, str) and value.strip():
                    return value
        return None
