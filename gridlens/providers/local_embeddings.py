"""Pinned local SentenceTransformers embeddings; runtime never downloads or truncates."""

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from gridlens.config import Settings
from gridlens.contracts import DTO, EmbeddingBatch
from gridlens.db import now
from gridlens.errors import AppError

# BGE v1.5 model card: instruction for short retrieval queries; passages take none.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DOCUMENT_PREFIX = ""
MAX_BATCH = 16
MANIFEST_NAME = "gridlens-model.json"
# Files needed by SentenceTransformers; skips duplicate ONNX/PyTorch-bin weights.
ALLOW_PATTERNS = ["*.json", "*.txt", "model.safetensors", "1_Pooling/*"]
COMMIT = re.compile(r"^[0-9a-f]{40}$")

Loader = Callable[[Path], object]
Downloader = Callable[..., str]


class ModelManifest(DTO):
    # Prefixes are exact model inputs; the shared DTO default would strip their spaces.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    model_id: str = Field(min_length=1)
    revision: str = Field(pattern=COMMIT.pattern)
    tokenizer_revision: str = Field(pattern=COMMIT.pattern)
    snapshot_path: str = Field(min_length=1)
    dimensions: int = Field(gt=0)
    max_seq_length: int = Field(gt=0)
    query_prefix: str
    document_prefix: str
    normalize: Literal[True] = True
    prepared_at: str


def manifest_path(settings: Settings) -> Path:
    return settings.local_model_dir / MANIFEST_NAME


def read_manifest(settings: Settings) -> ModelManifest:
    try:
        manifest = ModelManifest.model_validate_json(manifest_path(settings).read_text("utf-8"))
    except (OSError, ValueError):
        raise AppError(
            "LOCAL_MODEL_MISSING", "The local embedding model has not been prepared."
        ) from None
    if manifest.model_id != settings.embedding_model:
        raise AppError("LOCAL_MODEL_MISSING", "The prepared model differs from EMBEDDING_MODEL.")
    if settings.embedding_revision and manifest.revision != settings.embedding_revision:
        raise AppError(
            "LOCAL_MODEL_MISSING", "The prepared model revision differs from EMBEDDING_REVISION."
        )
    return manifest


def model_dimension(model) -> int | None:
    # SentenceTransformers 6 renamed the accessor; accept either supported name.
    for name in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
        if callable(getattr(model, name, None)):
            return getattr(model, name)()
    return None


def sentence_transformer_loader(path: Path):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise AppError(
            "LOCAL_MODEL_MISSING", "Install the models extra to use local embeddings."
        ) from None
    try:
        return SentenceTransformer(
            str(path), device="cpu", local_files_only=True, trust_remote_code=False
        )
    except (OSError, ValueError):
        raise AppError(
            "LOCAL_MODEL_MISSING", "The local embedding model files could not be loaded."
        ) from None


def prepare_model(
    settings: Settings,
    *,
    downloader: Downloader | None = None,
    loader: Loader = sentence_transformer_loader,
    clock: Callable[[], str] = now,
) -> ModelManifest:
    """Explicit, user-invoked download; the only code path that may reach the model hub."""
    if downloader is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            raise AppError(
                "LOCAL_MODEL_MISSING", "Install the models extra before preparing the model."
            ) from None
        downloader = snapshot_download
    settings.local_model_dir.mkdir(parents=True, exist_ok=True)
    snapshot = Path(
        downloader(
            repo_id=settings.embedding_model,
            revision=settings.embedding_revision or None,
            cache_dir=str(settings.local_model_dir),
            allow_patterns=ALLOW_PATTERNS,
        )
    ).resolve()
    revision = snapshot.name
    if not COMMIT.match(revision) or not snapshot.is_relative_to(settings.local_model_dir):
        raise AppError("LOCAL_MODEL_MISSING", "The downloaded model revision is not a commit.")
    if settings.embedding_revision and revision != settings.embedding_revision:
        raise AppError("LOCAL_MODEL_MISSING", "The downloaded revision differs from the pin.")
    model = loader(snapshot)
    dimensions = model_dimension(model)
    if dimensions != settings.embedding_dimensions:
        raise AppError(
            "EMBEDDING_DIMENSION_MISMATCH", "The model dimension differs from configuration."
        )
    manifest = ModelManifest(
        model_id=settings.embedding_model,
        # Tokenizer files are part of the same pinned repository snapshot.
        revision=revision,
        tokenizer_revision=revision,
        snapshot_path=str(snapshot.relative_to(settings.local_model_dir)),
        dimensions=dimensions,
        max_seq_length=int(model.max_seq_length),
        query_prefix=QUERY_PREFIX,
        document_prefix=DOCUMENT_PREFIX,
        prepared_at=clock(),
    )
    manifest_path(settings).write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    return manifest


class LocalEmbeddingProvider:
    """Loads the prepared model on first use, never during construction or UI rerun."""

    def __init__(self, settings: Settings, *, loader: Loader = sentence_transformer_loader):
        if not settings.normalize_embeddings or settings.embedding_device != "cpu":
            raise AppError("CONFIG_INVALID", "Local embeddings require normalized CPU inference.")
        self.settings = settings
        self.loader = loader
        self._manifest: ModelManifest | None = None
        self._model = None

    @property
    def manifest(self) -> ModelManifest:
        if self._manifest is None:
            self._manifest = read_manifest(self.settings)
        return self._manifest

    @property
    def model_id(self) -> str:
        return self.manifest.model_id

    @property
    def revision(self) -> str:
        return self.manifest.revision

    def identity(self) -> dict:
        """Everything that changes vectors; documents and queries share it."""
        m = self.manifest
        return {
            "model_id": m.model_id,
            "revision": m.revision,
            "tokenizer_revision": m.tokenizer_revision,
            "dimensions": m.dimensions,
            "max_seq_length": m.max_seq_length,
            "query_prefix": m.query_prefix,
            "document_prefix": m.document_prefix,
            "normalize": m.normalize,
            "device": self.settings.embedding_device,
        }

    def fingerprint(self) -> str:
        canonical = json.dumps(self.identity(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Token counts including special tokens, without truncation."""
        tokenizer = self._load().tokenizer
        encoded = tokenizer(list(texts), add_special_tokens=True, truncation=False, verbose=False)[
            "input_ids"
        ]
        return [len(ids) for ids in encoded]

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        """Character spans of the text's tokens, without special tokens."""
        tokenizer = self._load().tokenizer
        if not getattr(tokenizer, "is_fast", False):
            raise AppError("LOCAL_MODEL_MISSING", "The model tokenizer cannot report offsets.")
        encoded = tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            return_offsets_mapping=True,
            verbose=False,
        )
        return [(int(start), int(end)) for start, end in encoded["offset_mapping"]]

    def embed(self, texts: list[str], role: Literal["document", "query"]) -> EmbeddingBatch:
        if role not in {"document", "query"}:
            raise AppError("INVALID_INPUT", "Embedding role must be document or query.")
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise AppError("INVALID_INPUT", "Embedding inputs must be nonempty text.")
        manifest = self.manifest
        prefix = manifest.query_prefix if role == "query" else manifest.document_prefix
        inputs = [prefix + text for text in texts]
        started = time.perf_counter()
        counts = self.count_tokens(inputs)
        if any(count > manifest.max_seq_length for count in counts):
            raise AppError(
                "EMBEDDING_INPUT_TOO_LONG",
                f"An input exceeds the {manifest.max_seq_length}-token model limit.",
            )
        model = self._load()
        vectors: list[list[float]] = []
        for start in range(0, len(inputs), MAX_BATCH):
            batch = inputs[start : start + MAX_BATCH]
            output = model.encode(
                batch,
                batch_size=MAX_BATCH,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            rows = [[float(n) for n in row] for row in output]
            if len(rows) != len(batch):
                raise AppError("EMBEDDING_INVALID", "The model returned the wrong vector count.")
            vectors.extend(rows)
        self._validate(vectors)
        return EmbeddingBatch(
            vectors=vectors,
            model_id=manifest.model_id,
            revision=manifest.revision,
            dimensions=self.settings.embedding_dimensions,
            role=role,
            local_token_count=sum(counts),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _validate(self, vectors: list[list[float]]) -> None:
        for vector in vectors:
            if len(vector) != self.settings.embedding_dimensions:
                raise AppError(
                    "EMBEDDING_DIMENSION_MISMATCH", "The model returned an unexpected dimension."
                )
            if not all(math.isfinite(n) for n in vector):
                raise AppError("EMBEDDING_INVALID", "The model returned a non-finite value.")
            if abs(math.sqrt(sum(n * n for n in vector)) - 1) > 1e-3:
                raise AppError("EMBEDDING_INVALID", "The model returned an unnormalized vector.")

    def _load(self):
        if self._model is None:
            manifest = self.manifest
            path = (self.settings.local_model_dir / manifest.snapshot_path).resolve()
            if not path.is_relative_to(self.settings.local_model_dir) or not path.is_dir():
                raise AppError("LOCAL_MODEL_MISSING", "The prepared model files are missing.")
            model = self.loader(path)
            if model_dimension(model) != self.settings.embedding_dimensions:
                raise AppError(
                    "EMBEDDING_DIMENSION_MISMATCH",
                    "The model dimension differs from configuration.",
                )
            self._model = model
        return self._model
