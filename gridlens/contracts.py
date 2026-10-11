"""Shared, strict DTOs. The same contracts are used by real and fake providers."""

import math
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class IngestionStatus(StrEnum):
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class VersionStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class SearchHitDTO(DTO):
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    snippet: str
    provider_rank: int = Field(ge=1)
    publisher: str | None = None
    published_at: str | None = None
    source_type: Literal[
        "policy", "technical", "paper", "industry_report", "product", "unknown"
    ] = "unknown"
    jurisdiction: Literal["NZ", "US", "GLOBAL", "UNKNOWN"] = "UNKNOWN"
    metadata_evidence: dict = Field(default_factory=dict)


class DiscoveryRequest(DTO):
    topic: str = Field(min_length=3, max_length=500)
    region: Literal["NZ", "US", "ALL"] = "NZ"
    source_types: list[Literal["policy", "technical", "paper", "industry_report", "product"]] = (
        Field(default_factory=list)
    )

    @model_validator(mode="after")
    def unique_source_types(self):
        if len(set(self.source_types)) != len(self.source_types):
            raise ValueError("Source types must be unique")
        return self


class SearchCandidate(DTO):
    source_id: str
    title: str
    url: str
    snippet: str
    publisher: str | None = None
    published_at: str | None = None
    source_type: Literal[
        "policy", "technical", "paper", "industry_report", "product", "unknown"
    ] = "unknown"
    jurisdiction: Literal["NZ", "US", "GLOBAL", "UNKNOWN"] = "UNKNOWN"
    relevance_reason: str
    provider_rank: int = Field(ge=1)


class SearchRunDetail(DTO):
    run_id: str
    operation_key: str
    topic: str
    queries: list[str] = Field(min_length=1, max_length=3)
    status: Literal["completed", "partial", "failed"]
    calls_used: int = Field(ge=0, le=3)
    candidates: list[SearchCandidate] = Field(max_length=10)
    error_codes: list[str] = Field(default_factory=list)
    mode: Literal["fixture", "live"]


class FetchedDocument(DTO):
    requested_url: str
    final_url: str
    content_type: Literal["text/html", "application/pdf"]
    body: bytes = Field(min_length=1)
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fetched_at: str
    redirect_count: int = Field(ge=0, le=3)


class Locator(DTO):
    kind: Literal["pdf", "html"]
    file_page: int | None = Field(default=None, ge=1)
    printed_page: str | None = None
    section_title: str | None = None
    paragraph_index: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def location_required(self):
        if self.kind == "pdf" and self.file_page is None:
            raise ValueError("PDF requires a file page")
        if self.kind == "html" and self.paragraph_index is None:
            raise ValueError("HTML requires a paragraph index")
        return self


class ParsedSegment(DTO):
    segment_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    heading_path: list[str] = Field(default_factory=list)
    locator: Locator
    warnings: list[str] = Field(default_factory=list)


class VersionPreview(DTO):
    version_id: str
    source_id: str
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: Literal["text/html", "application/pdf"]
    segments: list[ParsedSegment] = Field(min_length=1)
    metadata: dict
    extraction_notes: list[str]
    review_status: Literal["pending"] = "pending"
    reused: bool = False


class MetadataCorrection(DTO):
    title: str = Field(min_length=1, max_length=500)
    publisher: str | None = Field(default=None, max_length=300)
    published_at: str | None = Field(default=None, max_length=50)
    jurisdiction: Literal["NZ", "US", "GLOBAL", "UNKNOWN"]
    source_type: Literal["policy", "technical", "paper", "industry_report", "product", "unknown"]

    @model_validator(mode="after")
    def blank_optional_fields_are_unknown(self):
        for name in ("publisher", "published_at"):
            if getattr(self, name) == "":
                object.__setattr__(self, name, None)
        return self


class ReviewResult(DTO):
    version_id: str
    review_status: ReviewStatus
    ingestion_status: IngestionStatus
    version_status: VersionStatus
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_snapshot_sha256: str | None = None
    changed: bool


class IngestionResult(DTO):
    version_id: str
    run_id: str | None = None
    status: Literal["completed", "failed", "noop"]
    ingestion_status: IngestionStatus
    version_status: VersionStatus
    expected_chunks: int = Field(default=0, ge=0)
    indexed_chunks: int = Field(default=0, ge=0)
    error_code: str | None = None


class ChunkDTO(DTO):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    chunk_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    # Exact source text (citation target); embedding_text adds only heading context.
    text: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_text: str = Field(min_length=1)
    heading_path: list[str] = Field(default_factory=list)
    token_count: int = Field(gt=0)
    source_segment_ids: list[str] = Field(min_length=1)
    locator: Locator
    index_fingerprint: str = Field(min_length=1)


class EmbeddingBatch(DTO):
    vectors: list[list[float]]
    model_id: str
    revision: str
    dimensions: int = Field(gt=0)
    role: Literal["document", "query"]
    local_token_count: int = Field(ge=0)
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_vectors(self):
        if not self.vectors or any(
            len(v) != self.dimensions or any(not math.isfinite(n) for n in v) for v in self.vectors
        ):
            raise ValueError(
                "Embedding vectors must be nonempty, finite and dimensionally consistent"
            )
        return self


class VectorHit(DTO):
    chunk_id: str
    distance: float


class RetrievalContext(DTO):
    chunks: list[ChunkDTO]
    eligible_version_ids: list[str]
    filters: dict
    index_fingerprint: str
    diagnostics: dict = Field(default_factory=dict)


class Evidence(DTO):
    chunk_id: str = Field(min_length=1)
    support_quote: str = Field(min_length=1, max_length=400)


class Claim(DTO):
    claim_id: str = Field(min_length=1)
    kind: Literal["fact", "inference"]
    text: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class MissingEvidence(DTO):
    reason_type: Literal[
        "no_evidence",
        "partial_coverage",
        "jurisdiction_mismatch",
        "freshness_unverified",
        "conflicting_evidence",
        "needs_external_validation",
    ]
    subquestion: str = Field(min_length=1)
    needed_evidence: str = Field(min_length=1)
    suggested_queries: list[str] = Field(min_length=1)


class AnswerDraft(DTO):
    evidence_status: Literal["answered", "partial", "insufficient"]
    claims: list[Claim]
    limitations: list[str]
    missing_evidence: list[MissingEvidence]

    @model_validator(mode="after")
    def status_consistency(self):
        if self.evidence_status in {"answered", "partial"} and not self.claims:
            raise ValueError("Answered and partial drafts require claims")
        if self.evidence_status in {"partial", "insufficient"} and not self.missing_evidence:
            raise ValueError("Partial and insufficient drafts require missing evidence")
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("Claim IDs must be unique")
        return self


class AnswerEnvelope(DTO):
    qa_id: str
    execution_status: Literal["completed", "failed", "stale_context"]
    evidence_status: Literal["answered", "partial", "insufficient"] | None
    claims: list[Claim]
    limitations: list[str]
    citations: list[dict]
    gaps: list[dict]
    error: dict | None
    mode: Literal["fixture", "live"]

    @model_validator(mode="after")
    def no_success_on_error(self):
        if self.execution_status != "completed" and (
            self.claims or self.evidence_status or self.gaps
        ):
            raise ValueError("Failed operations cannot contain a normal answer or knowledge gaps")
        return self


class AccountSummary(DTO):
    registration_id: str
    label: str
    connected: bool


class AuthState(DTO):
    status: Literal["connected", "needs_login", "permission_missing", "usage_limited"]
    account: AccountSummary | None = None


class ModelChoice(DTO):
    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class CredentialRecord(DTO):
    # SecretStr protects repr/model_dump; storage must explicitly unwrap only for writing.
    issuer: Literal["https://auth.openai.com"] = "https://auth.openai.com"
    subject: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    ext_agent_host_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    email: str | None = Field(default=None, repr=False)
    access_token: SecretStr | None = Field(default=None, repr=False)
    refresh_token: SecretStr | None = Field(default=None, repr=False)
    id_token: SecretStr | None = Field(default=None, repr=False)
    scopes: list[str]
    expires_at: int = Field(ge=0)
    saved_at: str

    @model_validator(mode="after")
    def issued_client_required(self):
        if self.client_id == "dynamic_agent_client":
            raise ValueError("An issued client ID is required for stored registrations")
        return self


class SearchProvider(Protocol):
    def search(self, query: str, limit: int) -> list[SearchHitDTO]: ...


class Tokenizer(Protocol):
    def count_tokens(self, texts: list[str]) -> list[int]: ...

    def token_offsets(self, text: str) -> list[tuple[int, int]]: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str], role: Literal["document", "query"]) -> EmbeddingBatch: ...


class AnswerProvider(Protocol):
    def generate(self, question: str, context: RetrievalContext) -> AnswerDraft: ...


class VectorStore(Protocol):
    def upsert(self, chunks: list[ChunkDTO], vectors: list[list[float]]) -> None: ...
    def query(
        self, vector: list[float], eligible_version_ids: list[str], k: int
    ) -> list[VectorHit]: ...
    def stored_ids(self, version_id: str) -> set[str]: ...
    def delete_version(self, version_id: str) -> None: ...


class CredentialStore(Protocol):
    def save(self, record: CredentialRecord) -> str: ...
    def load(self, registration_id: str) -> CredentialRecord: ...
    def summaries(self) -> list[AccountSummary]: ...
    def clear_tokens(self, registration_id: str) -> None: ...


class SessionProvider(Protocol):
    def access_token(self, registration_id: str) -> SecretStr: ...
