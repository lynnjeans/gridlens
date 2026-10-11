"""Approved snapshot → chunks → vectors → atomic Ready/Active publication.

SQLite and Chroma share no transaction: vectors are written first and the database
publishes last. Vectors left by a failed run never gain eligibility, because retrieval
eligibility is decided only by SQLite.
"""

import json
from collections.abc import Callable
from uuid import uuid4

from gridlens.contracts import (
    ChunkDTO,
    EmbeddingProvider,
    IngestionResult,
    Tokenizer,
    VectorStore,
)
from gridlens.db import Database, now
from gridlens.documents.chunking import chunk_segments, index_fingerprint
from gridlens.errors import AppError
from gridlens.services.review import ReviewService

UPSERT_BATCH = 16


class IngestionService:
    def __init__(
        self,
        db: Database,
        review: ReviewService,
        *,
        embeddings: EmbeddingProvider,
        tokenizer: Tokenizer,
        vectors: VectorStore,
        embedding_identity: dict,
        dimensions: int,
        chunk_tokens: int,
        chunk_overlap: int,
        max_input_tokens: int,
        before_publish: Callable[[str], None] | None = None,
    ):
        self.db = db
        self.review = review
        self.embeddings = embeddings
        self.tokenizer = tokenizer
        self.vectors = vectors
        self.embedding_identity = embedding_identity
        self.dimensions = dimensions
        self.chunk_tokens = chunk_tokens
        self.chunk_overlap = chunk_overlap
        self.max_input_tokens = max_input_tokens
        self.fingerprint = index_fingerprint(embedding_identity, chunk_tokens, chunk_overlap)
        # Test hook between verification and publication; never set by the app.
        self.before_publish = before_publish

    def ingest(self, version_id: str, operation_key: str) -> IngestionResult:
        if not operation_key.strip():
            raise AppError("INVALID_INPUT", "An operation key is required.")
        started = self._start(version_id, operation_key)
        if isinstance(started, IngestionResult):
            return started
        run_id, approved_hash = started
        try:
            chunks = self._prepare_chunks(version_id, run_id)
            self._index(chunks, run_id)
            self._verify(version_id, chunks, run_id)
            if self.before_publish:
                self.before_publish(version_id)
            return self._publish(version_id, run_id, approved_hash, len(chunks))
        except AppError as error:
            return self._fail(version_id, run_id, error.code)
        except Exception:
            self._fail(version_id, run_id, "INGESTION_FAILED")
            raise AppError("INGESTION_FAILED", "Indexing failed unexpectedly.") from None

    def purge_vectors(self, version_id: str) -> bool:
        """Best-effort cleanup after revocation; eligibility never depends on it."""
        try:
            self.vectors.delete_version(version_id)
        except Exception:
            return False
        return True

    def _start(self, version_id: str, operation_key: str):
        with self.db.transaction() as c:
            existing = c.execute(
                "SELECT * FROM ingestion_runs WHERE operation_key=?", (operation_key,)
            ).fetchone()
            if existing:
                if existing["version_id"] != version_id:
                    raise AppError("INVALID_INPUT", "The operation key belongs to another version.")
                if existing["status"] == "processing":
                    raise AppError("INGESTION_IN_PROGRESS", "This document is already indexing.")
                return self._run_result(c, existing)
            version = c.execute(
                "SELECT * FROM document_versions WHERE id=?", (version_id,)
            ).fetchone()
            if version is None:
                raise AppError("VERSION_NOT_FOUND", "The document version does not exist.")
            if (
                version["review_status"] != "approved"
                or version["approved_snapshot_sha256"] != version["snapshot_sha256"]
            ):
                raise AppError("REVIEW_REQUIRED", "Only an approved snapshot can be indexed.")
            if version["version_status"] == "superseded":
                raise AppError("REVIEW_REQUIRED", "A superseded version cannot be indexed again.")
            if version["ingestion_status"] == "ready":
                if version["index_fingerprint"] != self.fingerprint:
                    raise AppError(
                        "INDEX_CONFIG_MISMATCH",
                        "This version was indexed with another configuration.",
                    )
                return self._version_result(version, "noop")
            if (
                version["ingestion_status"] == "processing"
                or c.execute(
                    "SELECT 1 FROM ingestion_runs WHERE version_id=? AND status='processing'",
                    (version_id,),
                ).fetchone()
            ):
                raise AppError("INGESTION_IN_PROGRESS", "This document is already indexing.")
            attempt = (
                c.execute(
                    "SELECT COUNT(*) FROM ingestion_runs WHERE version_id=?", (version_id,)
                ).fetchone()[0]
                + 1
            )
            run_id = str(uuid4())
            c.execute(
                "INSERT INTO ingestion_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    operation_key,
                    version_id,
                    "chunking",
                    "processing",
                    attempt,
                    0,
                    0,
                    now(),
                    None,
                    None,
                ),
            )
            c.execute(
                "UPDATE document_versions SET ingestion_status='processing' WHERE id=?",
                (version_id,),
            )
            return run_id, version["snapshot_sha256"]

    def _prepare_chunks(self, version_id: str, run_id: str) -> list[ChunkDTO]:
        segments = self.review.load_snapshot(version_id)
        chunks = chunk_segments(
            version_id,
            segments,
            self.tokenizer,
            embedding_identity=self.embedding_identity,
            chunk_tokens=self.chunk_tokens,
            chunk_overlap=self.chunk_overlap,
            max_input_tokens=self.max_input_tokens,
        )
        model_id = self.embedding_identity.get("model_id", "unknown")
        with self.db.transaction() as c:
            # Chunks of a published version may be cited, so content is never rewritten;
            # only provenance missing from rows indexed before migration 002 is filled in.
            c.executemany(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE "
                "SET source_segment_ids_json=excluded.source_segment_ids_json "
                "WHERE chunks.source_segment_ids_json='[]'",
                [
                    (
                        chunk.chunk_id,
                        version_id,
                        self.fingerprint,
                        chunk.ordinal,
                        chunk.text,
                        json.dumps(chunk.heading_path, ensure_ascii=False),
                        chunk.locator.model_dump_json(exclude_none=True),
                        chunk.text_sha256,
                        chunk.token_count,
                        model_id,
                        self.dimensions,
                        json.dumps(chunk.source_segment_ids),
                    )
                    for chunk in chunks
                ],
            )
            stored = {
                row["id"]
                for row in c.execute(
                    "SELECT id FROM chunks WHERE version_id=? AND index_fingerprint=?",
                    (version_id, self.fingerprint),
                )
            }
            if stored != {chunk.chunk_id for chunk in chunks}:
                raise AppError("CHUNK_MISMATCH", "Saved chunks differ from the expected chunks.")
            c.execute(
                "UPDATE ingestion_runs SET stage='embedding', expected_chunks=? WHERE id=?",
                (len(chunks), run_id),
            )
        return chunks

    def _index(self, chunks: list[ChunkDTO], run_id: str) -> None:
        indexed = 0
        for start in range(0, len(chunks), UPSERT_BATCH):
            batch = chunks[start : start + UPSERT_BATCH]
            embedded = self.embeddings.embed([chunk.embedding_text for chunk in batch], "document")
            if len(embedded.vectors) != len(batch) or embedded.dimensions != self.dimensions:
                raise AppError(
                    "EMBEDDING_INVALID", "The embedding batch does not match the chunks."
                )
            self.vectors.upsert(batch, embedded.vectors)
            indexed += len(batch)
            with self.db.transaction() as c:
                c.execute(
                    "UPDATE ingestion_runs SET indexed_chunks=? WHERE id=?", (indexed, run_id)
                )

    def _verify(self, version_id: str, chunks: list[ChunkDTO], run_id: str) -> None:
        with self.db.transaction() as c:
            c.execute("UPDATE ingestion_runs SET stage='verifying' WHERE id=?", (run_id,))
        # Compare ID sets, not counts: same size with different IDs is still incomplete.
        if self.vectors.stored_ids(version_id) != {chunk.chunk_id for chunk in chunks}:
            raise AppError("INDEX_INCOMPLETE", "The index does not match the expected chunks.")

    def _publish(self, version_id, run_id, approved_hash, chunk_count) -> IngestionResult:
        with self.db.transaction() as c:
            version = c.execute(
                "SELECT * FROM document_versions WHERE id=?", (version_id,)
            ).fetchone()
            run = c.execute("SELECT status FROM ingestion_runs WHERE id=?", (run_id,)).fetchone()
            if (
                version["review_status"] != "approved"
                or version["snapshot_sha256"] != approved_hash
                or version["approved_snapshot_sha256"] != approved_hash
                or version["ingestion_status"] != "processing"
                or run["status"] != "processing"
            ):
                raise AppError("REVIEW_CHANGED", "The review changed during indexing.")
            c.execute(
                "UPDATE document_versions SET version_status='superseded' "
                "WHERE source_id=? AND version_status='active' AND id!=?",
                (version["source_id"], version_id),
            )
            c.execute(
                "UPDATE document_versions SET ingestion_status='ready', version_status='active', "
                "index_fingerprint=? WHERE id=?",
                (self.fingerprint, version_id),
            )
            c.execute(
                "UPDATE ingestion_runs SET stage='published', status='completed', finished_at=? "
                "WHERE id=?",
                (now(), run_id),
            )
        return IngestionResult(
            version_id=version_id,
            run_id=run_id,
            status="completed",
            ingestion_status="ready",
            version_status="active",
            expected_chunks=chunk_count,
            indexed_chunks=chunk_count,
        )

    def _fail(self, version_id: str, run_id: str, code: str) -> IngestionResult:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE ingestion_runs SET status='failed', finished_at=?, error_code=? "
                "WHERE id=? AND status='processing'",
                (now(), code, run_id),
            )
            # Only this run's processing state is cleared; the old Active version is untouched.
            c.execute(
                "UPDATE document_versions SET ingestion_status='failed' "
                "WHERE id=? AND ingestion_status='processing'",
                (version_id,),
            )
            return self._run_result(
                c, c.execute("SELECT * FROM ingestion_runs WHERE id=?", (run_id,)).fetchone()
            )

    def _run_result(self, c, run) -> IngestionResult:
        version = c.execute(
            "SELECT * FROM document_versions WHERE id=?", (run["version_id"],)
        ).fetchone()
        return IngestionResult(
            version_id=run["version_id"],
            run_id=run["id"],
            status=run["status"],
            ingestion_status=version["ingestion_status"],
            version_status=version["version_status"],
            expected_chunks=run["expected_chunks"],
            indexed_chunks=run["indexed_chunks"],
            error_code=run["error_code"],
        )

    @staticmethod
    def _version_result(version, status) -> IngestionResult:
        return IngestionResult(
            version_id=version["id"],
            status=status,
            ingestion_status=version["ingestion_status"],
            version_status=version["version_status"],
        )
