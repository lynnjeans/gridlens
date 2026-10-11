"""Local persistent Chroma index; vectors are always supplied explicitly.

Chroma is an index, not an authority: metadata holds only identifiers, chunk text and
review eligibility stay in SQLite, and every query requires an explicit version whitelist.
"""

import math
from pathlib import Path

from gridlens.contracts import ChunkDTO, VectorHit
from gridlens.errors import AppError

COLLECTION_PREFIX = "gridlens-"


def _explicit_vectors_only():
    from chromadb.api.types import EmbeddingFunction

    class ExplicitVectorsOnly(EmbeddingFunction):
        """Replaces Chroma's default ONNX model so nothing is embedded or downloaded."""

        def __init__(self):
            pass

        def __call__(self, input):
            raise AppError("VECTOR_STORE_FAILED", "Vectors must be supplied explicitly.")

        @staticmethod
        def name() -> str:
            return "gridlens-explicit-vectors"

        def get_config(self) -> dict:
            return {}

        @staticmethod
        def build_from_config(config):
            return ExplicitVectorsOnly()

        def default_space(self):
            return "cosine"

        def supported_spaces(self):
            return ["cosine"]

    return ExplicitVectorsOnly()


class ChromaVectorStore:
    """One collection per index fingerprint; opened lazily, never on UI rerun."""

    def __init__(self, path: Path, index_fingerprint: str, dimensions: int):
        if len(index_fingerprint) != 64 or dimensions <= 0:
            raise AppError("INDEX_CONFIG_MISMATCH", "The index configuration is invalid.")
        self.path = Path(path)
        self.index_fingerprint = index_fingerprint
        self.dimensions = dimensions
        self._collection = None

    @property
    def collection_name(self) -> str:
        return COLLECTION_PREFIX + self.index_fingerprint[:48]

    def upsert(self, chunks: list[ChunkDTO], vectors: list[list[float]]) -> None:
        if not chunks or len(chunks) != len(vectors):
            raise AppError("INDEX_INCOMPLETE", "Chunks and vectors must match one to one.")
        if any(chunk.index_fingerprint != self.index_fingerprint for chunk in chunks):
            raise AppError("INDEX_CONFIG_MISMATCH", "A chunk belongs to another index.")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise AppError("INDEX_INCOMPLETE", "Chunk IDs must be unique within a write.")
        for vector in vectors:
            self._check_vector(vector)
        collection = self._open()
        batch = self._max_batch()
        for start in range(0, len(chunks), batch):
            part = chunks[start : start + batch]
            self._call(
                collection.upsert,
                ids=[chunk.chunk_id for chunk in part],
                embeddings=[[float(n) for n in v] for v in vectors[start : start + batch]],
                metadatas=[
                    {
                        "version_id": chunk.version_id,
                        "ordinal": chunk.ordinal,
                        "index_fingerprint": chunk.index_fingerprint,
                    }
                    for chunk in part
                ],
            )

    def query(
        self, vector: list[float], eligible_version_ids: list[str], k: int
    ) -> list[VectorHit]:
        # An empty whitelist means no eligible evidence, never "search everything".
        allowed = sorted({version_id for version_id in eligible_version_ids if version_id})
        if not allowed or k <= 0:
            return []
        self._check_vector(vector)
        result = self._call(
            self._open().query,
            query_embeddings=[[float(n) for n in vector]],
            n_results=k,
            where={"version_id": {"$in": allowed}},
            include=["distances", "metadatas"],
        )
        hits = [
            VectorHit(chunk_id=chunk_id, distance=float(distance))
            for chunk_id, distance, metadata in zip(
                result["ids"][0], result["distances"][0], result["metadatas"][0], strict=True
            )
            # Defence in depth: never return an ID outside the whitelist.
            if metadata and metadata.get("version_id") in allowed
        ]
        return sorted(hits, key=lambda hit: (hit.distance, hit.chunk_id))

    def stored_ids(self, version_id: str) -> set[str]:
        result = self._call(self._open().get, where={"version_id": version_id}, include=[])
        return set(result["ids"])

    def delete_version(self, version_id: str) -> None:
        self._call(self._open().delete, where={"version_id": version_id})

    def _open(self):
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            raise AppError(
                "VECTOR_STORE_FAILED", "Install the vectors extra to use the local index."
            ) from None
        self.path.mkdir(parents=True, exist_ok=True)
        client = self._call(
            chromadb.PersistentClient,
            path=str(self.path),
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
        collection = self._call(
            client.get_or_create_collection,
            self.collection_name,
            embedding_function=_explicit_vectors_only(),
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"index_fingerprint": self.index_fingerprint, "dimensions": self.dimensions},
        )
        metadata = collection.metadata or {}
        space = (collection.configuration or {}).get("hnsw", {}) or {}
        if (
            metadata.get("index_fingerprint") != self.index_fingerprint
            or metadata.get("dimensions") != self.dimensions
            or space.get("space") != "cosine"
        ):
            raise AppError(
                "INDEX_CONFIG_MISMATCH", "The local index was built with another configuration."
            )
        self._client = client
        self._collection = collection
        return collection

    def _max_batch(self) -> int:
        try:
            return max(1, int(self._client.get_max_batch_size()))
        except Exception:
            return 1000

    def _check_vector(self, vector) -> None:
        if len(vector) != self.dimensions:
            raise AppError("INDEX_CONFIG_MISMATCH", "The vector dimension differs from the index.")
        if not all(math.isfinite(float(n)) for n in vector):
            raise AppError("INDEX_INCOMPLETE", "Vectors must contain finite numbers.")

    @staticmethod
    def _call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except AppError:
            raise
        except Exception:
            raise AppError(
                "VECTOR_STORE_FAILED", "The local vector index operation failed."
            ) from None
