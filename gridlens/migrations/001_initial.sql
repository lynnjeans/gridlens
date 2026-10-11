CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE search_runs (
    id TEXT PRIMARY KEY, operation_key TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL, filters_json TEXT NOT NULL CHECK(json_valid(filters_json)),
    queries_json TEXT NOT NULL CHECK(json_valid(queries_json)), provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','completed','partial','failed')),
    calls_used INTEGER NOT NULL DEFAULT 0 CHECK(calls_used >= 0),
    started_at TEXT NOT NULL, finished_at TEXT, error_code TEXT
);
CREATE TABLE sources (
    id TEXT PRIMARY KEY, canonical_url TEXT NOT NULL UNIQUE, original_url TEXT NOT NULL,
    title TEXT NOT NULL, publisher TEXT,
    source_type TEXT NOT NULL CHECK(source_type IN
      ('policy','technical','paper','industry_report','product','unknown')),
    jurisdiction TEXT NOT NULL CHECK(jurisdiction IN ('NZ','US','GLOBAL','UNKNOWN')),
    topics_json TEXT NOT NULL CHECK(json_valid(topics_json)),
    access_status TEXT NOT NULL CHECK(access_status IN ('unknown','readable','reference_only','failed')),
    created_at TEXT NOT NULL
);
CREATE TABLE search_hits (
    id TEXT PRIMARY KEY, search_run_id TEXT NOT NULL REFERENCES search_runs(id),
    source_id TEXT NOT NULL REFERENCES sources(id), rank INTEGER NOT NULL CHECK(rank > 0),
    snippet TEXT NOT NULL, relevance_reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    UNIQUE(search_run_id,source_id)
);
CREATE TABLE document_versions (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    raw_sha256 TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
    raw_path TEXT NOT NULL, segments_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    published_at TEXT, fetched_at TEXT NOT NULL,
    extraction_notes_json TEXT NOT NULL CHECK(json_valid(extraction_notes_json)),
    review_status TEXT NOT NULL CHECK(review_status IN ('pending','approved','rejected','revoked')),
    ingestion_status TEXT NOT NULL CHECK(ingestion_status IN
      ('not_started','processing','ready','failed')),
    version_status TEXT NOT NULL CHECK(version_status IN ('candidate','active','superseded')),
    approved_snapshot_sha256 TEXT, index_fingerprint TEXT, created_at TEXT NOT NULL,
    UNIQUE(source_id,snapshot_sha256),
    CHECK(version_status != 'active' OR ingestion_status = 'ready')
);
CREATE UNIQUE INDEX one_active_version_per_source ON document_versions(source_id)
    WHERE version_status = 'active';
CREATE INDEX version_eligibility ON document_versions(review_status,ingestion_status,version_status);
CREATE TABLE review_events (
    id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES document_versions(id),
    action TEXT NOT NULL CHECK(action IN ('approve','reject','revoke','reopen')),
    reviewer_label TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL,
    CHECK(action != 'reject' OR length(trim(reason)) > 0 AND reason IS NOT NULL)
);
CREATE TABLE ingestion_runs (
    id TEXT PRIMARY KEY, operation_key TEXT NOT NULL UNIQUE,
    version_id TEXT NOT NULL REFERENCES document_versions(id), stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing','completed','failed')),
    attempt INTEGER NOT NULL CHECK(attempt >= 1),
    expected_chunks INTEGER NOT NULL CHECK(expected_chunks >= 0),
    indexed_chunks INTEGER NOT NULL CHECK(indexed_chunks >= 0),
    started_at TEXT NOT NULL, finished_at TEXT, error_code TEXT
);
CREATE UNIQUE INDEX one_running_ingestion ON ingestion_runs(version_id) WHERE status = 'processing';
CREATE TABLE chunks (
    id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES document_versions(id),
    index_fingerprint TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal >= 0), text TEXT NOT NULL,
    heading_path_json TEXT NOT NULL CHECK(json_valid(heading_path_json)),
    locator_json TEXT NOT NULL CHECK(json_valid(locator_json)), text_sha256 TEXT NOT NULL,
    token_count INTEGER NOT NULL CHECK(token_count > 0), embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL CHECK(embedding_dimension > 0),
    UNIQUE(version_id,index_fingerprint,ordinal)
);
CREATE TABLE qa_records (
    id TEXT PRIMARY KEY, operation_key TEXT NOT NULL UNIQUE, question TEXT NOT NULL,
    filters_json TEXT NOT NULL CHECK(json_valid(filters_json)),
    execution_status TEXT NOT NULL CHECK(execution_status IN ('completed','failed','stale_context')),
    evidence_status TEXT CHECK(evidence_status IN ('answered','partial','insufficient')),
    answer_json TEXT CHECK(answer_json IS NULL OR json_valid(answer_json)),
    context_chunk_ids_json TEXT NOT NULL CHECK(json_valid(context_chunk_ids_json)),
    context_version_ids_json TEXT NOT NULL CHECK(json_valid(context_version_ids_json)),
    model_id TEXT, output_mode TEXT CHECK(output_mode IN ('schema','prompt_json_validated','fixture')),
    account_registration_ref TEXT, prompt_version TEXT NOT NULL, index_fingerprint TEXT,
    created_at TEXT NOT NULL, latency_ms INTEGER NOT NULL CHECK(latency_ms >= 0),
    usage_json TEXT NOT NULL CHECK(json_valid(usage_json)), error_code TEXT,
    CHECK(execution_status = 'completed' OR (evidence_status IS NULL AND answer_json IS NULL))
);
CREATE TABLE citations (
    id TEXT PRIMARY KEY, qa_id TEXT NOT NULL REFERENCES qa_records(id), claim_ref TEXT NOT NULL,
    chunk_id TEXT NOT NULL REFERENCES chunks(id), quoted_span TEXT NOT NULL,
    locator_snapshot_json TEXT NOT NULL CHECK(json_valid(locator_snapshot_json)),
    source_metadata_snapshot_json TEXT NOT NULL CHECK(json_valid(source_metadata_snapshot_json)),
    UNIQUE(qa_id,claim_ref,chunk_id)
);
CREATE TABLE knowledge_gaps (
    id TEXT PRIMARY KEY, qa_id TEXT NOT NULL REFERENCES qa_records(id), gap_key TEXT NOT NULL,
    question TEXT NOT NULL, scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
    reason_type TEXT NOT NULL CHECK(reason_type IN
      ('no_evidence','partial_coverage','jurisdiction_mismatch','freshness_unverified',
       'conflicting_evidence','needs_external_validation')),
    missing_evidence TEXT NOT NULL,
    suggested_queries_json TEXT NOT NULL CHECK(json_valid(suggested_queries_json)),
    status TEXT NOT NULL CHECK(status IN ('open','resolved','dismissed')),
    resolution_note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(status != 'resolved' OR (resolution_note IS NOT NULL AND length(trim(resolution_note)) > 0))
);
CREATE UNIQUE INDEX unique_open_gap ON knowledge_gaps(gap_key) WHERE status = 'open';
CREATE TABLE app_state (key TEXT PRIMARY KEY, value_json TEXT NOT NULL CHECK(json_valid(value_json)));

