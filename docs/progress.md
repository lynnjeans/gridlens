# GridLens implementation progress

Date: 2026-10-11, Pacific/Auckland. Application: `gridlens/` in the Seen Ventures
project workspace. Synced `sources/` files were not changed.

## T06 — Tavily search adapter

Status: **implemented and verified offline**. The adapter uses the documented Tavily
Search endpoint with basic/general search, explicit result limits and generated answer,
raw content, images and automatic parameters disabled. It maps only candidate metadata
and safe snippets, skips malformed individual records, and maps authorization, quota,
HTTP and timeout failures to stable application errors without implicit retries.

`tests/unit/test_tavily.py`: **9 passed**. Ruff check and format check passed for the
adapter and its offline/live tests. The explicit live smoke test exists but was not run
because `TAVILY_API_KEY` is not configured. No real search calls or research records
were created. Next task: T07 search orchestration and persistence.

## T07 — Search orchestration and persistence

Status: **implemented and verified offline**. One user operation creates up to three
meaning-preserving queries, spends no more than three provider calls, canonicalizes
public URLs while preserving functional query parameters, removes common tracking
parameters, merges duplicates and stores at most ten candidates. SearchRun, SearchHit
and Source records are committed together after provider work. Completed operation keys
are persistent and replay without another provider call. Partial and failed runs retain
safe error codes, and unknown publication dates remain null.

Discovery unit and database integration suites: **11 passed**. They cover URL boundaries,
query generation, duplicates, stable ranking, limits, partial/all-failed behavior,
manual pending leads and idempotence after constructing a new service instance. No live
provider was used. Next task: T08 Discover UI.

## T08 — Discover UI and source selection

Status: **implemented and verified offline**. Discover now submits a validated topic,
region and source-type selection to the discovery service. It shows candidate metadata,
search snippets as non-evidence, relevance reasons and original links; empty, partial,
failed and missing-key states are distinct. A normal Streamlit rerun reads session/SQLite
state without repeating the provider operation. Search candidates and manually entered
public URLs can be selected for Review. Manual URLs are saved only as pending leads: no
content fetch, document version, approval or knowledge-base ingestion occurs.

Discover/navigation UI suites: **10 passed**. Full offline regression after T06–T08:

```text
.venv/bin/python -m pytest -q
67 passed, 1 deselected in 0.77s
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
47 files already formatted
.venv/bin/python -m pip check
No broken requirements found.
```

The deselected test is the explicit Tavily live smoke. No `TAVILY_API_KEY` was configured,
so no real search relevance or provider account behavior was validated. Human research
acceptance was not run. The application is still local and uncommitted/unpushed. Next
milestone: T09–T14 for bounded capture, HTML/PDF extraction, immutable snapshots and
human review.

## T09 — Bounded public document capture

Status: **implemented and verified offline**. `DocumentFetcher` validates HTTP(S),
userinfo, standard ports and every DNS address before each request and redirect. It
allows at most three manually checked redirects, disables automatic following, limits
declared, streamed and decompressed bytes, enforces elapsed time, accepts only HTML or
PDF (with PDF magic validation), and returns final URL, normalized type, timestamp and
SHA-256. Safe application errors cover DNS, access, missing documents, rate limits,
timeouts, unsupported types and upstream failures.

`tests/unit/test_fetch.py`: **24 passed**. Full offline regression: **91 passed, 1 live
deselected**; Ruff and format checks passed. All fetch tests use HTTP and DNS mocks; no
arbitrary website was contacted. This is a local-app SSRF boundary, not a claim of
production-grade DNS rebinding isolation. Next tasks: T10/T11 parsing.

## T10 — HTML body and paragraph extraction

Status: **implemented and verified offline**. The deterministic parser prefers
`main`/`article`, removes scripts, styles, navigation and other non-content nodes,
and falls back to body paragraphs with an explicit warning. Each paragraph retains
its heading path and one-based locator. Numbers, conditions and Unicode are preserved.
Tables carry a warning that relationships were not reconstructed. Text that resembles
instructions remains inert document text, and empty pages return `HTML_EMPTY` rather
than substituting a search snippet.

`tests/unit/test_html_parser.py`: **5 passed**. Full regression: **96 passed, 1 live
deselected**; Ruff and format checks passed. Next task: T11 PDF parsing.

## T11 — PDF text and page extraction

Status: **implemented and verified offline**. PDF parsing runs in a terminable spawned
subprocess with a page limit and caller timeout. Text is emitted as deterministic
segments with one-based physical `file_page` locators; it does not invent printed page
numbers. Every segment warns that complex tables and multi-column reading order need
checking against the original. Scanned/empty, corrupt, encrypted, over-limit and timed-out
documents return stable errors; OCR remains outside scope.

`tests/unit/test_pdf_parser.py`: **6 passed**. Full offline regression: **102 passed,
1 live deselected**; Ruff, format and dependency checks passed. Next task: T12 immutable
capture snapshots.

## T12 — Immutable review snapshots

Status: **implemented and verified offline**. Capture dispatches bounded HTML/PDF results
to the matching parser and computes snapshot identity from semantic segments, reviewed
metadata and the parser version. Fetch timestamps, raw hashes and temporary segment IDs
do not affect identity. Raw bytes and canonical segment JSON are written with same-directory
temporary files and atomic replacement under controlled hash paths before the Pending/
Candidate database version is committed. Duplicate identities reuse the first immutable
files; changed content or reviewed metadata creates a new version. Failures mark the lead
failed and do not create an approvable partial version.

`tests/integration/test_snapshots.py`: **6 passed**. Full offline regression: **108 passed,
1 live deselected**; Ruff, format and dependency checks passed. The service is not yet
connected to Review; that occurs in T14 after the T13 review state machine.

## T13 — Human review state machine

Status: **implemented and verified offline**. Approve validates the expected preview hash,
stored raw hash, parsed body and recomputed semantic snapshot identity before binding the
approved hash. Reject requires a reason. Revoke immediately changes the authoritative
SQLite review state, so an otherwise Ready/Active version is excluded from retrieval.
Reopen is limited to Rejected/Revoked non-superseded versions and clears approval/index
state back to Pending/Candidate/Not started. Actual transitions append one review event
in the same transaction; exact repeats are idempotent and event-write failure rolls back
the state update.

`tests/integration/test_review.py`: **6 passed**. Full offline regression: **114 passed,
1 live deselected**; Ruff, format and dependency checks passed. Next task: T14 Review UI.

## T14 — Review page

Status: **implemented and verified offline**. Review lists captured versions (pending
first), captures the selected source only on an explicit button click, shows the verified
segment text with locators, extraction limits, original/redirect links, snapshot hash,
status and review history. Pending versions accept metadata corrections (title,
publisher, date, jurisdiction, source type); the service recomputes the snapshot hash
and the page binds actions to the hash the reviewer opened. If the stored hash changes,
the page shows a stale warning, disables approval and requires "Reload preview". An
unreadable or tampered snapshot shows an error and cannot be approved. Reject requires a
reason; approved versions can be revoked and rejected/revoked ones reopened. Reruns
do not repeat actions or events. Fixture mode uses a synthetic `FakeDocumentFetcher`;
live mode uses the bounded `DocumentFetcher`. Ingestion after approval is not wired yet
(T18); the page says indexing becomes available later.

`tests/ui/test_review_page.py`: **8 passed** (named to avoid a pytest basename clash with
`tests/integration/test_review.py`, which now has **7 passed**). Full offline
regression: **123 passed, 1 live deselected**; Ruff, format and pip check passed. One
early run of the new UI file failed once in 10.7s on the first test and did not repeat in
six later runs (likely a cold-start AppTest timeout). No manual browser check, live
capture or real source review was run. At the user's request T13 and T14 were committed
and pushed to `origin/master`. Next task: T16 local embeddings (T16 → T15, T17 → T18).

## T16 — Local embeddings and model preparation

Status: **implemented and verified offline and with the real local model**.
`LocalEmbeddingProvider` loads a prepared SentenceTransformers snapshot by local path
with `local_files_only=True`, `trust_remote_code=False` and CPU inference, only on first
use (importing the app does not import torch). It rejects empty input, counts tokens with
the model's own tokenizer including special tokens and rejects inputs over the model limit
before encoding (no truncation), encodes in batches of at most 16 with normalization, and
validates vector count, dimension, finite values and unit norm. Queries use the BGE v1.5
model-card instruction prefix; documents use none. The fingerprint covers model,
revision, tokenizer revision, dimensions, limit, prefixes, normalization and device.
Missing manifest/files or a revision differing from `EMBEDDING_REVISION` raises
`LOCAL_MODEL_MISSING`. Fixture mode still uses the fake provider; the local provider is
not yet wired into bootstrap or ingestion (T18).

`gridlens prepare-model` is the only download path. It fetches only the files needed by
SentenceTransformers into `LOCAL_MODEL_DIR` (default git-ignored `models/`), requires a
40-hex commit, checks the dimension, and writes `models/gridlens-model.json`.

With the user's approval: the `models` extra was split into `embeddings`
(`sentence-transformers>=6.1,<7`) and `vectors` (chromadb, still for T17).
`.venv/bin/uv pip compile pyproject.toml --extra dev --extra auth --extra embeddings
--python .venv/bin/python --output-file requirements.lock` added sentence-transformers
6.1.0, torch 2.14.1, transformers 5.19.0, huggingface-hub 1.33.0 and their dependencies
(existing pins unchanged), installed with `uv pip install -r requirements.lock`. The lock
is resolved for this macOS/Python 3.12 environment. A dry run listed 10 files (134.4 MB);
`prepare-model` then recorded revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, 384 dimensions, 512 tokens.

Checks: `tests/unit/test_embeddings.py` **17 passed** (injected fake model).
`pytest -m local_model` with IP sockets still blocked: **2 passed** — 384-dim normalized
vectors, reproducible output, over-long input rejected; a grid query scored 0.656 against
a grid passage and 0.258 against an unrelated one. Full offline regression **140 passed,
3 deselected**; Ruff, format and pip check passed. Before asking, one `pip download` probe
resolved sentence-transformers 6.1.0 metadata and failed before saving a file. No ChatGPT
login, Chroma or ingestion was run. At the user's request T16 was committed and pushed
to `origin/master`. Next task: T15 chunking.

## T15 — Deterministic token chunking

Status: **implemented and verified offline and with the real local tokenizer**.
`gridlens/documents/chunking.py` (`segment-pack-v1`) groups consecutive segments by PDF
file page or HTML heading path, packs whole segments (blank-line joined) while the
embedding input — heading context + text, counted with special tokens by the model
tokenizer — fits `CHUNK_TOKENS`, and splits only a single over-budget segment into token
windows with `CHUNK_OVERLAP`. Windows are cut at tokenizer character offsets, so each
chunk `text` is an exact source substring (citation target); `embedding_text` adds only
the heading context. Over-long headings are left out of the embedding input but kept in
`heading_path`. Chunks never cross a page, section, document or version.
`index_fingerprint` hashes the embedding identity (model, revision, tokenizer revision,
dimensions, limit, prefixes, normalization, device), chunker version, size and overlap;
`chunk_id` hashes version, fingerprint, ordinal and text SHA-256 as canonical JSON.

Interface changes: `ChunkDTO` gained `ordinal`, `text_sha256`, `embedding_text`,
`heading_path` (whitespace preserved); new `Tokenizer` protocol; `LocalEmbeddingProvider`
gained `identity()` and `token_offsets()`; fixture `FakeTokenizer` and fake identity.

Checks: `tests/unit/test_chunking.py` **14 passed**. `pytest -m local_model` (IP sockets
blocked) **3 passed**, including the real BGE tokenizer at 350/50 on English and Chinese
long pages: 15 chunks, max 350 tokens, counts matching the real tokenizer, all embedded.
Full offline regression **154 passed, 4 deselected**; Ruff, format and pip check passed.
Not yet wired into ingestion (T18). At the user's request T15 was committed and pushed. Next task: T17 Chroma.

## T17 — Chroma vector store adapter

Status: **implemented and verified offline with a real temporary Chroma**.
`ChromaVectorStore` opens a `PersistentClient` lazily (never on construction or UI rerun)
with anonymized telemetry off, one cosine collection per index fingerprint
(`gridlens-` + 48 hex), and a custom embedding function that refuses to embed, so Chroma's
default ONNX model is never used or downloaded. Vectors are always passed explicitly.
Metadata holds only `version_id`, `ordinal`, `index_fingerprint`; no chunk text is stored.
Queries require a non-empty version whitelist (`$in`), return nothing for an empty one,
and re-check each hit's version. Fingerprint, dimension or space mismatches raise
`INDEX_CONFIG_MISMATCH`; Chroma errors map to `VECTOR_STORE_FAILED`. Writes reject count
mismatch, duplicate IDs and non-finite values and use the client's max batch size.

With the user's approval: `vectors` extra installed. `uv pip compile ... --extra
embeddings --extra vectors` added chromadb 1.5.9 and 38 new packages (onnxruntime
1.31.0, grpcio 1.84.0, kubernetes 37.0.1, opentelemetry 1.45.1, ...); existing pins
unchanged; `uv pip install -r requirements.lock`; pip check passed.

`tests/integration/test_vector_store.py`: **9 passed** (temporary real Chroma, IP sockets
blocked, default embedding function patched to fail if called). No `~/.cache/chroma` was
created. Full offline regression **163 passed, 4 deselected**; `local_model` 3 passed;
Ruff, format and pip check passed. Not yet wired into bootstrap or ingestion (T18).
At the user's request T17 was committed and pushed. Next task: T18 ingestion and atomic publication.

## T18 — Ingestion and atomic publication

Status: **implemented and verified offline and end-to-end with the real local model**.
`IngestionService.ingest(version_id, operation_key)` follows spec §7.3: a short
`BEGIN IMMEDIATE` transaction requires Approved with matching approved/current hash,
refuses superseded versions, returns `noop` for Ready with the same fingerprint (and
`INDEX_CONFIG_MISMATCH` for another), rejects a second processing run
(`INGESTION_IN_PROGRESS`, backed by the unique processing index) and creates the run.
It then loads the verified snapshot, chunks it, saves chunk rows with INSERT OR IGNORE
(cited chunks are never rewritten) and checks the saved ID set, embeds and upserts in
batches of 16 recording `indexed_chunks`, and compares the Chroma ID set with the
expected set (not counts). One publish transaction re-checks approval/hash/run state,
supersedes the source's old Active version and marks this version Ready/Active and the
run completed. Any failure marks only the run and this version's ingestion as failed;
the approval and the old Active version stay. Operation keys replay their result.

Wiring: `Container.ingestion`. Fixture mode uses the fake embedder/tokenizer with a
persistent Chroma at `data/fixture/chroma` (replacing the per-rerun in-memory fake);
live mode enables ingestion only after `prepare-model`, using `LocalEmbeddingProvider`
and Chroma at `data/live/chroma`. Building the container loads neither torch nor chromadb.
Review runs one ingestion after a successful approval (spinner, success/warning notice)
and shows "Retry indexing" for approved versions whose ingestion failed or never ran.

Checks: `tests/integration/test_ingestion.py` **10 passed** (fault injection at the
embedding, upsert, verification and publication stages, revocation before publish,
a second tab, old-Active retention and supersession, publish rollback via trigger).
`tests/ui/test_review_page.py` **11 passed** (3 new). `pytest -m local_model` (IP sockets
blocked) **4 passed**, including live-mode wiring with the real BGE model and Chroma:
2 chunks published and found by a whitelisted query; an empty whitelist returned nothing.
Full offline regression **176 passed, 5 deselected**; Ruff, format and pip check passed.
Recovering processing runs left by a crash is T28. At the user's request T18 was
committed and pushed.
Next task: T20 approved-only retrieval (T34 OAuth is behind its D2 schedule).

## T34 — OAuth login and callback validation (awaiting real sign-in)

Status: **implemented and verified offline; real sign-in not run** (task `awaiting_input`).
Official sources re-checked 2026-10-11: the Sign in with ChatGPT sign-in, token
reference and errors pages, and `https://auth.openai.com/.well-known/openid-configuration`
(issuer, authorize/token endpoints, `jwks_uri` `/.well-known/jwks.json`, RS256, S256).

`gridlens/auth/oauth.py`: `CallbackListener` binds `127.0.0.1` (OS-chosen port) on
`/auth/callback`, accepts one callback and never logs request URLs. `OAuthLogin.begin`
creates a fresh state/nonce/PKCE verifier per attempt (S256, 5-minute expiry) and builds
the authorize URL: first registration with `dynamic_agent_client` + `agent_name_hint`
and the stable `ext_agent_host_id`; returning sign-in with the issued client ID plus
`id_token_hint`/`login_hint`. `complete` consumes the attempt once, checks expiry and
state (constant time) before anything else, stops on callback errors without exchanging,
requires an issued client ID on registration (never storing `dynamic_agent_client`) and
rejects a different one on return, exchanges the code with the issued ID, identical
redirect URI, verifier and resource (no secret), verifies the ID token with PyJWT against
the JWKS (RS256, issuer, audience = issued ID, exp, nonce), and for returning sign-in
requires the original subject. Only then are credentials saved. Following the official
errors guidance, a missing `chatgpt.tokens.use.direct` keeps the sign-in with
`plan_usage_enabled=False` (the spec previously said reject). `run_browser_login` starts
the listener before opening the browser and always closes it (timeout → `OAUTH_TIMEOUT`).
CLI: `gridlens login [--account REG]`, live mode only, prints a redacted summary.

Checks: `tests/unit/test_oauth.py` **22 passed** (test-generated RSA keys, mocked token
endpoint, synthetic fixture JWKS). One listener test uses `enable_socket` restricted by
`allow_hosts(["127.0.0.1"])`; all other tests keep IP sockets blocked. Full offline
regression **198 passed, 6 deselected**; `local_model` 4 passed; Ruff, format and pip
check passed. Not run: real browser sign-in — the user chose to run it later with
`APP_MODE=live .venv/bin/python -m gridlens.cli login` (or `APP_MODE=live GRIDLENS_LIVE_LOGIN=1 .venv/bin/python -m pytest -m live -k login -s`). The account sidebar is T36. At the user's request the T34 offline implementation was
committed and pushed.

## T20 — Approved-only retrieval (2026-10-12)

Status: **implemented and verified offline and with the real local model**.
`RetrievalService.retrieve(question, RetrievalFilters)` validates a 3–2000 character
question, computes eligibility only from SQLite (`eligible_versions`: approved + matching
approved hash + Ready + Active + index fingerprint) and filters on the reviewed metadata
frozen with each version: NZ → NZ+GLOBAL, US → US+GLOBAL, GLOBAL → GLOBAL, ALL → all
including UNKNOWN; optional source types. With no eligible version it calls neither the
embedding model nor Chroma and reports `no_approved_sources` or `filters_excluded_all`
with per-region/type exclusion counts (metadata only). Otherwise it embeds the question
(role query), queries Top-10 with the version whitelist, loads authoritative chunk rows
from SQLite, drops unknown/other-index/ineligible IDs (`dropped_out_of_scope`), keeps
relevance order, skips the lower-ranked of adjacent overlapping windows (same version,
adjacent ordinal, shared segment), and selects at most 5 chunks within 4000 tokens. It
re-checks eligibility before returning; if everything selected became ineligible the
reason is `stale_context`. No reranker, hybrid search or confidence percentage.

Schema: migration `002_chunk_segments.sql` adds `chunks.source_segment_ids_json` (needed
for `ChunkDTO` provenance and overlap detection); the runner now applies numbered
migrations in order inside one transaction. Ingestion stores segment IDs and only fills
provenance for rows indexed before 002 (content is never rewritten); retrieval drops such
legacy rows with `dropped_without_provenance`. `Container.retrieval` is available
whenever ingestion is.

Checks: `tests/integration/test_retrieval.py` **9 passed** (real temporary Chroma with
stale vectors for revoked/superseded versions, spy providers, a store returning foreign
IDs, revocation during the query, reading-order store for overlap). `test_db.py` adds a
v1→v2 in-place upgrade test. `local_model` **4 passed** — live wiring returns the approved
"load forecast" chunk. Full offline regression **208 passed, 6 deselected**; Ruff, format
and pip check passed. At the user's request T20 was committed and pushed. Next: T19 Knowledge Base page or T35.

## T19 — Knowledge Base page (2026-10-12)

Status: **implemented and verified offline (AppTest); manual browser check not run**.
The page lists every version with review, ingestion and version status in separate
columns, reviewed region/type, a "Searchable" flag taken only from the SQLite eligibility
predicate, and a plain status (Waiting for review, Rejected, Approval revoked, Approved ·
not indexed yet / indexing (stage) / indexing failed (code) / indexed with another
configuration, Superseded, Searchable), plus counts. The detail view shows reviewed
metadata, extraction limits, the latest run's real stage and `indexed/expected` counts
(no percentages), and Retry (via `IngestionService`, fresh `kb-retry-<uuid>` operation key,
disabled while processing) and Revoke (via `ReviewService`, reviewer required, optional
reason) actions; "Reload status" re-reads state. Review and Knowledge Base now share
`ui/common.index_version`. `ResearchRepository.latest_ingestion_runs()` added.

Checks: `tests/ui/test_knowledge_base.py` **5 passed**; full offline regression **213
passed, 6 deselected**; Ruff, format and pip check passed. Not run: manual browser check.
Refresh to a new snapshot is T26. Committed and pushed under the user's "Auto, go to the
end" instruction. Next: T35 sessions (offline; real check needs the T34 sign-in).

## T35 — Session refresh, account switching and sign-out (awaiting real check)

Status: **implemented and verified offline; real refresh/sign-out not run** (task
`awaiting_input`, needs the T34 sign-in). Official profiles-and-sessions and
errors-and-recovery pages re-checked 2026-10-12.

`gridlens/auth/sessions.py` `SessionManager`: `select()` validates a connected
registration and writes `active.json` with an incremented epoch; a `SessionHandle`
from an older selection is rejected (`ACCOUNT_CHANGED`), so results and tokens never mix
across accounts. `access_token(handle)` returns the stored token unless it expires within
5 minutes; `refresh()` holds a per-registration `fcntl` lock (tabs and processes), reloads
the record, posts `grant_type=refresh_token` with the issued client ID, refresh token and
resource (no scope), validates the complete rotated set and replaces it atomically.
Terminal errors (`invalid_grant`, `refresh_token_reused`, …) clear tokens — keeping the ID
token only as a sign-in hint — and raise `AUTH_EXPIRED`; network/5xx/incomplete
responses keep credentials (`AUTH_REFRESH_UNAVAILABLE`, retryable); `invalid_client` →
`AUTH_CLIENT_INVALID`. `sign_out()` first deactivates the account, then revokes the
refresh token at the discovery `revocation_endpoint` (must be on the issuer) with up to 3
attempts and 1 s/2 s backoff on network/5xx, then clears access/refresh/ID tokens while
keeping the client ID and host ID; unconfirmed revocation is reported. CLI:
`gridlens logout --account <prefix>`.

Checks: `tests/unit/test_sessions.py` **19 passed** (rotation-enforcing mock server,
3-thread race → exactly one refresh). Full offline regression **232 passed, 7
deselected**; live tests skip without opt-in; Ruff, format and pip check passed. Not run:
real refresh/sign-out — after `gridlens login`, run `APP_MODE=live GRIDLENS_LIVE_SESSION=1 .venv/bin/python -m pytest -m live -k live_sessions -s`. Committed and pushed
(user's "Auto" instruction). Next: T36 account sidebar and model catalog.

## T36 — Account sidebar and model catalog (awaiting real check)

Status: **implemented and verified offline; real catalog not read** (task
`awaiting_input`, needs the T34 sign-in). Official models-and-inference page checked
2026-10-12.

`gridlens/auth/catalog.py`: `ModelCatalog.fetch(handle)` gets a token through
`SessionManager`, calls `GET https://api.openai.com/v1/models` with only the Bearer header,
keeps `visibility == "list"` entries in server order (dedupes, display name falls back to
slug), maps 401/403/429/other to `AUTH_EXPIRED` / `PLAN_PERMISSION_MISSING` /
`USAGE_LIMITED` / `MODEL_CATALOG_UNAVAILABLE`, and discards a response if the account
changed meanwhile. `gridlens/ui/account.py` (sidebar): fixture mode shows a disabled
sign-in; live mode offers Continue with ChatGPT (runs the T34 loopback login in-process),
an account picker (selection via `SessionManager.select`, which resets the catalog and
model choice), a model picker from that account's catalog only (loaded once per selection
and cached in session state without tokens; "Refresh models" reloads), a plan-usage
warning when the scope is missing, Reauthorize, Sign out (reports unconfirmed revocation),
Add another account, and the ChatGPT Usage link. `selected_model()` returns a model only if
it belongs to the current account's catalog and plan usage is granted.

Checks: `tests/unit/test_catalog.py` **8 passed**, `tests/ui/test_account.py` **5 passed**.
Full offline regression **245 passed, 7 deselected**; `local_model` 4 passed; Ruff,
format and pip check passed. Not run: a real catalog read and selection. Committed and
pushed (user's "Auto" instruction); the first push (649649b) carried only tasks.json
because a documentation script failed midway — fixed in the next commit. Next: T21.

## T21 — ChatGPT plan-usage streaming answer provider (awaiting real smoke)

Status: **implemented and verified offline; real generation not run** (task
`awaiting_input`). Official models-and-inference, preview-limitations and
errors-and-recovery pages checked 2026-10-12; they do not document `text.format` or usage
fields, so structured-output support must be confirmed on the real selected model.

`gridlens/providers/chatgpt_oauth.py` `ChatGPTAnswerProvider(sessions, handle, slug)`
implements `AnswerProvider.generate`. It refuses without the plan scope or when the
account changed, takes the token from `SessionManager`, and posts with raw httpx (no
SDK retries) to `/v1/responses` a body limited to model/instructions/input/store/stream/
text: `store=false`, `stream=true`, the `answer_v1` prompt as `instructions`, and one user
message whose text is a JSON object holding the question and evidence (so document text
is data). Output mode `auto` tries a strict `json_schema` and, only if the request is
rejected with a `text.*` parameter error before any stream, retries once in
`prompt_json_validated`; both modes require a strict `AnswerDraft` (no free text, no extra
URL/page fields). SSE is buffered (2 MB cap) until `response.completed`; `response.failed`
(usage limit → `USAGE_LIMITED`, not eligible / scope → `PLAN_PERMISSION_MISSING`,
invalid user → `AUTH_EXPIRED`), `response.incomplete`, malformed events, a dropped
connection or a stream without completion all raise. Admission 401/403/404/429/5xx map
to distinct errors without retry. `provider.last` records registration prefix, slug,
returned model, output mode, request ID, terminal event, usage and latency — never the
token. Prompt: `gridlens/prompts/answer_v1.txt` (packaged).

Checks: `tests/unit/test_answer_provider.py` **21 passed**. Full offline regression
**266 passed, 8 deselected**; Ruff, format and pip check passed. Not run: real answer
smoke (`APP_MODE=live GRIDLENS_LIVE_ANSWER=1 .venv/bin/python -m pytest -m live -k live_answer -s`, uses plan usage) and a rebuilt-wheel check of the packaged prompt.
Citation validation is T22. Committed and pushed (user's "Auto" instruction).

## T22 — Q&A service, citation checks and saving (2026-10-12)

Status: **implemented and verified offline**. `AnswerService.ask(question, filters,
operation_key, provider)` replays a stored result for a known operation key (no second
model call), retrieves approved context (T20), and answers `completed/insufficient`
without any model when nothing is eligible (reason → `no_evidence` or
`jurisdiction_mismatch`) or saves `stale_context` when retrieval found only revoked
evidence. Otherwise it generates at most twice: a format error (`OUTPUT_INVALID`) or a
citation problem (`services/citations.py`: chunk must be in this context and eligible,
quote must be a whitespace-normalized verbatim span) gets one repair attempt with the
reason; provider failures (usage, permission, timeout, incomplete stream …) are saved as
`failed` with their code — never as insufficient evidence — and not retried. Just before
saving, cited versions are re-checked against the SQLite eligibility predicate (revoked →
`stale_context`, no draft published). Citations are numbered by first appearance;
title, publisher, date, region, type, URLs, version ID, snapshot hash and locator come
from snapshots, never from the model. QA record + per-claim citation rows (+ a `gap_writer`
hook for T24) are written in one transaction; any failure rolls everything back
(`QA_SAVE_FAILED`). Records keep model, output mode, registration prefix, prompt version,
index fingerprint, latency, usage, request ID and attempt count.

Interfaces: `AnswerProvider.generate(..., repair=None)`; `AnswerEnvelope.missing_evidence`;
`Container.answer_service`. Checks: `tests/integration/test_answers.py` **15 passed**;
full offline regression **281 passed, 8 deselected**; `local_model` 4 passed; Ruff, format
and pip check passed. Citation checks prove provenance, not semantic entailment.
Committed and pushed (user's "Auto" instruction). Next: T23 Ask page.

## T23 — Ask page and citation viewer (2026-10-12)

Status: **implemented and verified offline (AppTest); live asking and manual browser check
not run**. The Ask tab has a question form with region (NZ/US include GLOBAL; ALL adds
UNKNOWN) and source types. The operation key stays in session state until the answer is
saved, and the page always renders from the stored QA record via `AnswerService.replay`,
so reruns never call the model. Answers show the evidence status (answered / partly
answered / insufficient), each claim labelled Fact or Inference with `[n]` markers,
limitations and missing evidence (always visible), and numbered source expanders with
the verbatim short quote, PDF file page (and printed page) or section › paragraph,
publisher/date/region/type, the supported claim IDs and the original link. Each render
re-checks current eligibility and marks citations from revoked/superseded versions as
historical. Failures (sign-in, permission, usage limit with usage link, incomplete stream,
format/citation rejection, timeout), stale context and invalid input are shown
distinctly; no retrieval distance is shown. A history picker re-renders earlier answers.
Live mode builds `ChatGPTAnswerProvider` from the sidebar's account/model selection.

Checks: `tests/ui/test_ask.py` **6 passed**; full offline regression **287 passed, 8
deselected**; Ruff, format and pip check passed. Committed and pushed (user's "Auto"
instruction). Next: T24 knowledge gaps.

## T24 — Knowledge gaps (2026-10-12)

Status: **implemented and verified offline**. `gridlens/services/gaps.py`: `gap_key` hashes
canonical JSON of the normalized question (whitespace and case only — numbers, negations
and place names still differ), canonical filters (region, sorted source types), reason
type and normalized subquestion. `GapService.write` is the `AnswerService.gap_writer`
hook, so gaps are saved in the same transaction as the QA record and citations, only for
completed answers: rule-generated gaps when nothing is eligible (`no_evidence`,
`jurisdiction_mismatch`) and the verified draft's `missing_evidence` otherwise. An open gap
with the same key is updated (latest QA, needed evidence, suggested queries, time)
instead of duplicated; closed gaps stay as history and a later miss opens a new record.
The subquestion is kept in `scope_json` so edits can recompute the key; editing, resolving
(non-empty note required), dismissing and reopening are explicit user actions with
uniqueness checks (`GAP_DUPLICATE`, `GAP_NOT_OPEN`, `RESOLUTION_NOTE_REQUIRED`).
Provider failures, citation failures and stale context create no gaps.

Checks: `tests/integration/test_gaps.py` **11 passed**; full offline regression **298
passed, 8 deselected**; Ruff, format and pip check passed. Committed and pushed (user's
"Auto" instruction). Next: T25 gap list and search entry.

## T25 — Gap list and follow-up search entry (2026-10-12)

Status: **implemented and verified offline (AppTest); manual browser check not run**.
The Knowledge gaps tab filters by Open/Resolved/Dismissed/All and shows, per gap, the
question, scope (region, types), a reason phrased against this knowledge base ("No
approved source covers this yet", "Approved sources are for another region", …), the
sub-question, the missing evidence, evidence already cited by the linked answer, and the
suggested searches. Users can edit reason/sub-question/missing evidence/searches (key
re-checked), mark resolved (note required), dismiss, and reopen closed gaps. "Use in
Discover" only stores the query; the Discover page fills its topic box from it on the next
visit and runs nothing until the user clicks Search.

Checks: `tests/ui/test_gaps_page.py` **4 passed** (search provider call count stays 0
while viewing gaps and prefilling Discover); full offline regression **302 passed, 8
deselected**; Ruff, format and pip check passed. Correction: when commit 3923e7e was
pushed, the full run actually had 1 collection error (the UI test was named
`tests/ui/test_gaps.py`, clashing with `tests/integration/test_gaps.py`) and my check
chain did not stop on it; the file was renamed and re-verified in the next commit. Committed and pushed (user's "Auto"
instruction). Next: T26 refresh and historical citation status.

## T26 — Refresh, version updates and historical citation status (2026-10-12)

Status: **implemented and verified offline**. Refresh ("Refresh from source" in the
Knowledge Base) recaptures the source: the snapshot now carries forward the reviewer's
metadata from the latest version (title, publisher, date, region, type), so unchanged
content is a no-op and only changed content creates a new pending candidate with no
inherited approval. **Behavior change:** an unreviewed change to the source table's labels
no longer creates a version; the T12 test was updated accordingly. Approved metadata is
corrected through `ReviewService.revise_metadata`, which adds a pending version with the
same files and a new hash while the approved version keeps serving. The live version shows
"update awaiting review" until the new one is approved and indexed (T18 then supersedes the
old one). Revoke commits in SQLite first, then `IngestionService.purge_vectors` tries to
delete the vectors; failure is reported and harmless because eligibility comes only from
SQLite, and revoking never restores an older version. Historical answers keep their text,
quotes and locations; `citations.source_statuses` recomputes current / superseded /
revoked / not_current on every view and Ask labels each citation.

Checks: `tests/integration/test_version_lifecycle.py` **3 passed**, Knowledge Base refresh
UI test added; full offline regression **306 passed, 8 deselected**; Ruff, format and pip
check passed. Committed and pushed (user's "Auto" instruction). Next: T27 export.

## T27 — Markdown research log export (2026-10-12)

Status: **implemented and verified offline; human readability check not run**.
`gridlens/services/export.py` `ExportService.export(ExportSelection)` produces UTF-8
Markdown with UTC and Pacific/Auckland time, mode (plus a synthetic-data warning in
fixture mode) and a "no generated conclusions" note. Selected sources are split into
current approved sources (with review events and notes), historical/not-current sources
(title, link, status only) and leads awaiting review (no document text). Selected answers
list claims with `[n]` markers, limitations, missing evidence and numbered citations with
locations and the source status at export time; quotes appear only for current or
superseded (labelled) sources; answers citing revoked sources are labelled historical,
their revoked quotes are omitted, and — a tightening found by testing — any claim whose
only sources are revoked/not current is omitted too, because claim wording can reproduce
the source. Open gaps (and selected gaps) are listed. All values are escaped (Markdown
punctuation; `<`/`>`/`&` as entities); only HTTP(S) URLs become links; no snapshot
paths, credentials or provider payloads are read. The Knowledge Base page has an export
form (sources, answers, open gaps) with "Prepare export" and a Markdown download.

Checks: `tests/integration/test_export.py` **6 passed**; full offline regression **312
passed, 8 deselected**; Ruff, format and pip check passed. I generated and read a sample
fixture export; the card's human check of an exported file was not run. Committed and
pushed (user's "Auto" instruction). Next: T28 recovery, limits and run records.

## T28 — Recovery, call limits and run records (2026-10-12)

Status: **implemented and verified offline**. Every ingestion and search run now holds an
OS `fcntl` lock file (`data/<mode>/locks/<kind>-<run>.lock`) for its whole duration.
`RecoveryService.recover()` (once per browser session in `app.py`, or `gridlens recover`)
tries each processing/running run's lock without blocking: if it can be taken the owner has
exited, so the run becomes `failed` with `INGESTION_INTERRUPTED` / `SEARCH_INTERRUPTED`
and a processing version becomes retryable `failed`; a lock held by a live process is left
alone. Nothing approved, indexed or answered is touched, and nothing is retried
automatically. Runs left by versions before T28 have no lock and count as interrupted.
`OperationLog` appends redacted JSON lines (`data/<mode>/logs/operations.jsonl`) with kind,
operation ID, stage, status, duration, call count, usage category (`local_inference`,
`search_quota`, `chatgpt_plan`, `fixture`, `none`), numeric usage and error code — never
questions, answers, documents or tokens. `install_log_redaction()` adds a redacting filter
(Bearer tokens, OAuth `code`/`state`/`nonce`/`id_token_hint`/`login_hint`, JWTs,
`*_token` values, `tvly-`/`sk-` keys) to the root and HTTP-client loggers. `gridlens doctor`
is offline and secret-free: config, data-dir write probe, schema currency, runs to recover
vs in progress, credential-dir owner-only permissions and registration count, installed
extras (found without importing) and the prepared model. Call budgets: raw httpx with no
hidden retries; answers ≤2 calls (format/citation repair only), searches ≤3 calls.

Checks: `tests/integration/test_recovery.py` **8 passed** (a real child process holds a
lock); full offline regression **320 passed, 8 deselected**; Ruff, format and pip check
passed. Committed and pushed (user's "Auto" instruction). Next: T29 evaluation tooling.

## T29 — Question bank and evaluation tooling (2026-10-12)

Status: **implemented and verified offline; no gold or human scores exist (by design)**.
`evals/questions.json` holds R01–R15 copied verbatim from PRD §15.2 (a test compares each
row with the PRD) with splits: R01–R08 formal, evidence expected; R09–R12 formal,
insufficient evidence expected; R13–R15 discussion only. `evals/gold.json` is an empty,
human-only template; no gold content was written.

`gridlens evaluate --mode fixture|live` (must match `APP_MODE`; live needs a selected
signed-in account and `--model` from its catalog) asks R01–R12 once each with per-run
operation keys and writes `artifacts/evals/<run>/report.json` (corpus fingerprint of the
eligible versions and snapshots, index fingerprint, model, output mode, prompt version,
retrieval and chunk parameters, per-case results and failures) plus a blank
`reviews.json`. `gridlens evaluate-score --run DIR` applies PRD §15.3: retrieval hit
(automatic, needs human gold passages, ≥7/8), answer quality (human 0/1/2, ≥7/8 twos),
insufficient-evidence handling (human, 4/4), citation coverage (human, 100%), citation
support (human, ≥90%) and citation traceability (automatic locatability, 100%, explicitly
not semantic support), each with numerator and denominator. Missing gold, missing or
invalid scores and zero denominators give `awaiting_input`; fixture runs are always
`fixture_only_not_acceptance`; reviewers are listed and self-review must be disclosed.

Checks: `tests/unit/test_evaluation.py` **14 passed**; a real fixture `evaluate` +
`evaluate-score` run on this machine printed the fixture warning and left every metric
`awaiting_input`. Full offline regression **334 passed, 8 deselected**; Ruff, format and
pip check passed. Committed and pushed (user's "Auto" instruction). Next: T30.

## T30 — End-to-end and trust-boundary regression (2026-10-12)

Status: **offline regression passed; human UI check and real-account regressions not run**.
`tests/integration/test_workflow.py` (1) runs search → select → capture → reviewed
metadata → approve → index → ask → gap → export → restart on synthetic data.
`tests/integration/test_trust_boundaries.py` (10) checks PRD §15.4 against the retrieval
context and stored rows: marker text in pending/rejected/failed-indexing/revoked
documents never reaches context (unapproved text is never chunked); a revoked source
used by an answer is no longer retrieved and shows as revoked in history; duplicate
URLs/recaptures/re-indexing add no versions or chunks; corrupt/scanned PDFs and empty
HTML never create versions; fabricated chunk IDs are rejected; instructions inside a
source stay JSON data (instructions unchanged, no tools, nothing auto-approved); a
partial index failure publishes nothing; a dropped ChatGPT stream saves a failure with no
answer or gaps and no tokens in the database or operation log. Authorization regressions
are covered by the offline OAuth/session/catalog/provider/account suites.

Checks: full non-live run **345 passed, 8 deselected**; `local_model` **4 passed**; Ruff,
format and pip check passed; logs in `artifacts/test-results/` (git-ignored). An
AI-driven browser walkthrough of the fixture flow (Discover → Review → approve/index →
Knowledge Base → Ask → citation) succeeded and is recorded in
`artifacts/test-results/ui-walkthrough-2026-10-12-T30.md`; it is not the human UI check.
No unresolved P0 defect was found. Synthetic results do not show real research quality.
Committed and pushed (user's "Auto" instruction). Next: T31 needs the user (real corpus,
sign-in, gold answers and human scoring).

## T31 / T32 — Acceptance and delivery status (2026-10-12)

**T31: awaiting_input.** Real-corpus acceptance needs the user: a Tavily key, the owner's
ChatGPT sign-in and model choice, ≥10 sources approved by a person, human-written gold for
R01–R12 and human (preferably teammate) scores. None exist, so no acceptance metric has
been produced. I did not approve sources, write gold answers or score anything. The
runbook is in `docs/HANDOFF.md` §5 and the T31 card.

**T32: documents done; delivery awaiting T31.** README rewritten to the real state
(install, run, fixture/live, live setup for Tavily, `prepare-model`, Continue with
ChatGPT / plan usage / usage link / refresh / sign-out, checks, evaluation, data
locations and backup). Added `docs/DEMO.md` (6–8 minute script with pre-demo checks; fixture
demos must say so) and `docs/KNOWN_LIMITATIONS.md` (unverified items with how to verify
them, product limits, engineering notes, next steps); `.env.example` now says
`CHATGPT_MODEL_SLUG` is unused. Clean environment: a fresh Python 3.12.14 venv built with
uv **offline from the local cache** (no downloads) installed `requirements.lock` and the
project; `uv pip check` found 125 compatible packages; from site-packages the packaged
prompt and migrations loaded and a fixture search → capture → approve → index → ask (1
citation) → export ran. **MVP acceptance cannot be claimed**: T31, the real-account checks
(T34–T36, T21) and the human UI checks have not been done.

## Repository publication — 2026-10-11

The user explicitly requested publication. Before committing, `origin` was verified as
`https://github.com/lynnjeans/gridlens.git`, `master` had no remote heads, ignored runtime
paths were checked, and a credential-pattern scan found only labelled synthetic test
values. The current implementation and synchronized documentation were committed and
pushed to `origin/master`. No pull request or deployment was created.

## Foundation milestone — T01–T05 and T33

Status: **implemented and verified offline**. All remaining application tasks
are still todo. This milestone provides the foundation, not a working research
assistant: search, review actions, ingestion, RAG, gaps and ChatGPT login remain
unconnected. The UI disables unavailable actions and says what is pending.

| Task | Result | Evidence |
| --- | --- | --- |
| T01 | Independent local Git repository, Python 3.12 package, locked dependencies, launcher and safe configuration | Editable install, clean wheel install, `pip check`, Git ignore verification |
| T02 | Validated configuration, DTOs, safe errors and provider protocols | Contract tests; storage isolation and malformed answer/vector rejection |
| T03 | All initial SQLite tables, constraints, forward-only atomic initialization, basic repositories | Persistence, FK, unique active version/open gap, transaction rollback and eligible-source tests |
| T04 | Synthetic HTML/PDF/scenario fixtures and deterministic fake providers | Fixture manifest, real synthetic JWKS signature verification, rotating-token samples, fault modes and network-block test |
| T05 | Four-page Streamlit navigation and dependency assembly | AppTest for all pages and rerun behavior; actual browser navigation across all four pages and gaps tab |
| T33 | Stable host ID and protected, atomic per-registration credential store | File permissions, concurrent creation/read, write failure, path/identity checks, isolation and token clearing tests |

### Verification actually run

Environment: Python **3.12.14**, Streamlit **1.65.0**, Pydantic **2.14.0**, SQLite
standard library. Full installed versions are in `requirements.lock`.

```text
.venv/bin/python -m pytest -q
42 passed in 0.45s
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
37 files already formatted
.venv/bin/python -m pip check
No broken requirements found.
.venv/bin/python -m gridlens.cli init-db
Database initialized (fixture).
```

`doctor` reported fixture mode, no search key, OAuth not implemented and no model
download. Tests use temporary storage and block IP sockets; Unix-domain sockets
are allowed only so Streamlit's local asyncio event loop can run. The explicit
network-block test still rejects an IP socket. No network-dependent app tests ran.

Dependency resolution used uv **0.13.0** in the project environment:

```text
uv pip compile pyproject.toml --extra dev --extra auth --output-file requirements.lock
uv pip sync --python .venv/bin/python requirements.lock
python -m pip install -e . --no-deps
python -m pip wheel --no-deps --wheel-dir artifacts/wheels .
```

A second clean virtual environment at ignored `artifacts/clean-env/` installed the
lock and built wheel; import, packaged migration loading and bootstrap were tested
outside the source package directory. Core/dev/auth dependencies are locked now;
the optional model extra will be locked when T16/T17 are implemented, avoiding an
unused torch/model installation in this milestone. Build-tool versions are not
application runtime dependencies.

Browser check: `http://127.0.0.1:8501`, bound to loopback. Discover, Review,
Knowledge Base, Ask & Gaps and the gaps tab visibly loaded without exceptions.
No real credentials or research sources were created. `git check-ignore` confirmed
runtime data, `.env` and `.venv` are excluded, while the auth source code is included.

### Corrections made during verification

- Allowed local Unix sockets for AppTest while continuing to block IP network access.
- Corrected `.gitignore` so runtime `/auth/` is excluded without hiding auth source code.
- Corrected an AppTest assertion to inspect the main page title separately from the sidebar.
- Added fixture auth-directory confinement and finite/dimensionally consistent vector checks.

### Limits and next tasks

- Real ChatGPT OAuth, plan permissions, model catalog, subscription inference and quota
  behavior: **not run; T34–T36/T21 remain todo**.
- Local BGE model installation and inference: **not run; T16 remains todo**.
- At this foundation checkpoint, search/capture/review were not implemented. T06–T08
  were completed in the later source-discovery milestone above; T09–T14 remain todo.
- Research acceptance T31: not run. No approved corpus, gold answers or human scores exist.
- Current Git state: origin is configured for lynnjeans/gridlens; no local commit, push, deployment or external messages.
- Protected storage currently targets macOS/Linux. Broader platform support needs a separate change.

The next milestone at this earlier checkpoint was T06–T08. It is now complete; current
next work is **T09–T14** for document capture and review. **T34** can still proceed independently.
No credential needs to be pasted into a conversation to implement offline adapters.

## Project repository linked — 2026-10-11

The user identified `https://github.com/lynnjeans/gridlens.git` as the project
repository. GitHub metadata and `git ls-remote` confirmed it is empty, with
`master` as its configured default branch. The local repository now uses that
URL for `origin` and the unborn local branch is named `master`. No files were
uploaded, no remote branches were changed and no GitHub pull request was created.

## AI handoff synchronized — 2026-10-11

Current-state audit confirms T01–T05 and T33 done, 30 tasks todo. Actual local Git
state: origin configured, master branch unborn, all application files untracked,
no commit or push. Repository linkage supersedes the earlier pre-link status.

Re-ran the existing baseline for handoff: 42 tests passed in 0.49s, Ruff check
passed, format check reported 37 files formatted, pip check passed. Doctor still
reports fixture mode, no search key, OAuth not implemented and no model download.
No live tests, model download, new browser check or research evaluation ran in
this documentation turn.

Added root AGENTS.md and docs/HANDOFF.md; updated README, execution guide and the
machine manifest so a successor starts at T06–T08 instead of repeating T01.
The application docs are authoritative. The output documentation mirror and ZIP
are refreshed snapshots; don't overwrite newer application docs with them.
A separate source handoff ZIP contains the current application and docs, excluding
Git metadata, virtual environments, runtime data/results and credentials.
No code behavior, task completion status or remote state was changed by this handoff.

## Standing documentation-sync instruction — 2026-10-11

The user requested automatic documentation updates after each feature. Root
AGENTS.md, the execution guide and HANDOFF now require updating task JSON/cards,
progress and handoff before reporting completion or starting the next feature.
Incomplete work and failed checks must also be recorded honestly. Interface/setup
changes additionally update the specification/README. Available output mirrors and
handoff archives are refreshed without runtime data or real credentials.
This records a development workflow preference, not a scheduled automation or a
GitHub push request. At the time of this documentation-only change, feature states were
6 done and 30 todo; the later discovery milestone supersedes that count.

## T37 — SerpApi search adapter — 2026-10-12

Status: **implemented and verified offline; live smoke not run.** The user declined to
attach a payment card for Tavily and chose SerpApi (Google results). Checked the official
SerpApi docs (search-api, api-status-and-error-codes) on 2026-10-12: `GET
https://serpapi.com/search`, `api_key` query-parameter authentication only, `organic_results`
fields, and a 200 response with "Google hasn't returned any results" for an empty search.

Changed files: `gridlens/providers/serpapi.py` (new), `gridlens/config.py`
(`SEARCH_PROVIDER`, `SERPAPI_API_KEY`, `search_api_key`), `gridlens/bootstrap.py` (builds only
the selected provider), `gridlens/services/discovery.py` (`provider_name` recorded in
`search_runs.provider`), `gridlens/oplog.py` (redacts `api_key=`), `gridlens/cli.py` (doctor
reports `search_provider`), `gridlens/ui/discover.py` (provider-neutral missing-key message),
`.env.example`, README, spec §2/§6.1/sources, and tests (`tests/unit/test_serpapi.py` new;
contracts, discovery, discover UI, recovery redaction/doctor, live smoke).

Mapping: title/link/snippet; `date` kept as display text; `source` is evidence only, never
the publisher. No `num`, no retries, no answer box. 401/403 → SEARCH_AUTH_FAILED, 429 →
RATE_LIMITED, 5xx → PROVIDER_UNAVAILABLE (retryable), other 4xx → SEARCH_REQUEST_INVALID,
other `error` bodies or missing results → PROVIDER_RESPONSE_INVALID. Default provider stays
`tavily`, so existing behavior is unchanged.

Checks: `tests/unit/test_serpapi.py` 12 passed; full offline suite **360 passed, 9
deselected**; Ruff check passed; format check 108 files; pip check passed.
Not run: real SerpApi smoke (`SERPAPI_API_KEY` not configured). Next: the user's live checks
(T34 → T35 → T36 → T21) and T31.

Live update (2026-10-12): the user ran the real SerpApi smoke with their own key —
**1 passed** in 1.39s, one search spent. It confirms authentication, the request and
response parsing; it does not count or judge results (T31 relevance labelling does).
The first attempt failed with `SocketBlockedError` before any request because the live
search smokes lacked `@pytest.mark.enable_socket`; added it to the Tavily and SerpApi
smokes. Offline suite unchanged: 360 passed, 9 deselected (network still blocked by default).

## Fix — persistent Review queue (T08/T14) — 2026-10-12

Status: **fixed and verified offline.** In live use the user selected several search
results, but Review showed none of them (at most the last). Cause: "Select for review"
stored one `session_state.selected_source_id`, overwritten by each click and lost on reload;
Review showed only that one uncaptured source. Now selections and manual URLs are added to a
persistent `review_queue` in SQLite `app_state` (no migration), deduplicated, in selection
order. Review lists every queued source under "Waiting for capture (N)" with Capture and
Remove from queue; a captured source leaves the queue. Action notices now render at the top
of Review. Selections made before the fix were never saved and must be re-selected.

Changed: `gridlens/repositories/sources.py`, `gridlens/ui/discover.py`, `gridlens/ui/review.py`,
`tests/ui/test_discover.py`, `tests/ui/test_review_page.py`, spec §UI table.
Checks: full offline suite **361 passed, 9 deselected**; Ruff check and format passed.
Not run: a human check in the live UI (the user can re-select results and open Review).

## Fix — PDF worker re-ran the app (T05/T11) — 2026-10-12

Status: **fixed and verified offline.** While the user captured a live PDF, the terminal
filled with `missing ScriptRunContext` warnings. Cause: PDF extraction runs in a `spawn`
worker, which re-imports the main script (`app.py`) as `__mp_main__`; the whole page then
executed in bare mode, including run recovery and the sidebar (which, once signed in, could
request the model catalog). `app.py` now wraps the page in `main()` behind
`if __name__ == "__main__"` (Streamlit executes the script as `__main__`). Regression test
`tests/ui/test_navigation.py::test_spawned_worker_import_does_not_run_the_app` imports it as
`__mp_main__` with `build_container`/`set_page_config` forbidden. The capture itself had
succeeded (one pending version). Checks: **362 passed, 9 deselected**; Ruff/format passed.
Not run: re-capturing a live PDF after the fix (the user should restart `./run.sh`).

## Review page steps (T14) — 2026-10-12

Status: **implemented and verified offline.** User feedback: documents to review were listed
below the capture queue, hard to find and to understand. Review now has three step options —
"1 · To capture (N)", "2 · To review (N)", "Reviewed (N)" — each with a one-line explanation.
A successful capture jumps to step 2 with that document open; approve/reject/revoke/reopen keep
the acted-on document in view in the step where it now belongs (so Retry indexing stays
visible). It opens on step 2 when anything is pending. Changed `gridlens/ui/review.py` and its
UI tests. Checks: **362 passed, 9 deselected**; Ruff/format passed. Not run: the user's look at
the restarted live app.

## Review preview layout (T14) — 2026-10-12

User feedback: the document text was squeezed into two-thirds of the width and very tall.
The document picker is now a full-width dropdown above the detail, so the detail uses the
whole row; the text sits in a 560px scroll box; hard line breaks from extraction are joined
within a paragraph for display only (snapshot and citations unchanged; the page says so).
Checked in a temporary fixture instance in the browser (full width, scroll box) and removed
its data afterwards. Checks: **363 passed, 9 deselected**; Ruff passed.

## Remembered reviewer label (T14/T19) — 2026-10-12

User feedback: the Reviewer label had to be typed again after every reload or restart.
Review and Knowledge Base now prefill it with the last label used on this machine, stored in
SQLite `app_state` as `pref:reviewer_label` when edited (trimmed; a UI convenience, not a
credential). An empty label still blocks review actions. Checks: **364 passed, 9 deselected**;
Ruff passed.

## Approval metadata check and Region label (T14/T26) — 2026-10-12

The user's first approved document kept region UNKNOWN although they had fixed title,
publisher and type: Approve uses saved metadata, and an unsaved form edit was silently
dropped. Above Approve the page now states the saved region and type, says unsaved edits are
not approved, and warns when region is UNKNOWN (excluded from NZ/US/GLOBAL-filtered
questions) or type is unknown (warning only). At the user's request the UI label
"Jurisdiction" is now "Region" in the Review and Knowledge Base forms (stored field unchanged).
The approved document still needs a corrected version (Knowledge Base → Propose corrected
metadata → Region NZ). Checks: **365 passed, 9 deselected**; Ruff passed.

## Live answer verified (T34/T36/T21) and citation display fix (T22) — 2026-10-12

The user signed in with their own ChatGPT account, chose `gpt-5.6-sol` from their catalog
in the live sidebar and asked, with region NZ: "What does the Optimal Protocol submission
recommend about decentralisation of the electricity system?" against one approved NZ policy
document (7 chunks). Result: execution completed, evidence `answered`, 6 fact claims,
output mode `schema`, 1 attempt, 45.3 s, 2,624 input + 1,579 output (89 reasoning) =
4,203 tokens. Every support quote passed the verbatim check. T34, T36 and T21 are now done
(live passed). The `-m live -k live_answer` pytest smoke was not run separately; T35
refresh/sign-out has not been verified live.

Defect found in that answer: one chunk often supports several claims with different quotes,
but each citation number kept only the first quote, so Sources showed one sentence for [3]
while three statements relied on other sentences of it, and markers repeated ("[3] [3] [3]").
Fix: Ask numbers statements ("1 · Fact"), shows each marker once, and lists under each source
every verified quote with the statement it supports; the research log export does the same.
Older answers render correctly because quotes come from the stored draft. The `citations`
table still holds one row per (answer, claim, chunk); the full quotes remain in
`answer_json.draft`. Human judgment of whether each quote semantically supports its claim is
still part of T31. Checks: **366 passed, 9 deselected**; Ruff/format passed.

## Discover results layout (T08) — 2026-10-14

User feedback: the search form and the results looked alike, and each result card was so tall
that several results meant a lot of scrolling. A divider and a `Search results` heading now
separate the results from the form. Each card is compact: a numbered bold title, one grey line
with publisher · date — snippet (cut to 220 characters), and one row with Open original,
Select for review and the relevance reason. Search-provided titles and snippets are escaped so
they render literally. Changed `gridlens/ui/discover.py` and `tests/ui/test_discover.py`.
Checked in a fixture instance in the browser (layout, Select for review queues the candidate).
Checks: **366 passed, 9 deselected**; Ruff, format and pip check passed. Not run: the user's look
at the restarted live app.

## Review document labels (T14) — 2026-10-14

User report: the Reviewed dropdown listed the same article twice and the second entry could
not be selected. They are two versions of one source: after approval the Region was corrected,
which created a new version that was approved; the earlier one is superseded (retrieval uses
only the active version, so answers were unaffected). Streamlit 1.65 maps a picked label back to
the first equal label, so identical labels made the second unreachable. Labels now start with
`Older version · ` for superseded versions and with `Snapshot <hash12> · ` if still equal, so they
are unique and visible in a narrow dropdown. Changed `gridlens/ui/review.py` and
`tests/ui/test_review_page.py`. Checks: **367 passed, 9 deselected**; Ruff, format and pip check
passed. Restarted the live app and confirmed in the browser that the older version opens
(viewing only).

## Plain version wording (T14) — 2026-10-14

User feedback: "superseded" is an unfamiliar word. The screens now show version states in plain
words: active → `current`, superseded → `older version`, candidate → `not yet in use`; the
Knowledge Base status reads `Older version: a newer one replaced it`. Stored values and
interfaces are unchanged (`VERSION_LABELS` in `gridlens/ui/common.py`, used by Review and
Knowledge Base). Checks: **367 passed, 9 deselected**; Ruff, format and pip check passed.
Restarted the live app; Review shows `version: current` (viewing only).

## Remove after a failed capture (T14) — 2026-10-14

User report: after "The source requires access that is not available." the Remove from queue
button disappeared. The capture error path used `continue`, which skipped drawing the button.
The button is now drawn before the capture result is handled. For errors a retry cannot fix
(`AppError.retryable` is false, e.g. access required, not found, unsupported type) the page adds
that trying again will not help and suggests removing the source or opening the original.
Sources are not removed automatically. Changed `gridlens/ui/review.py` and
`tests/ui/test_review_page.py` (new test). Checks: **368 passed, 9 deselected**; Ruff, format and
pip check passed. Restarted the live app and confirmed the Review page loads; Capture was not
clicked in live (it would fetch a real site).

## Extract wording and staying in step 1 (T14) — 2026-10-14

User feedback: "capture" is hard to understand, and extracting a source should not jump to
To review. On-screen wording now says extract: step `1 · To extract (N)`, button
`Extract text`, plus the Discover success message, sidebar note, timeout error and empty states
(internal keys and service names unchanged). After Extract text the page stays in step 1 with
"Text extracted. Read it in 2 · To review, then approve or reject." and the document is
preselected in step 2; other actions still follow the document to its step. Spec Review row and
README updated. Checks: **368 passed, 9 deselected**; Ruff, format and pip check passed.
Restarted the live app and confirmed the new wording (viewing only; Extract text not clicked
in live).

## Review step no longer jumps when counts change (T14) — 2026-10-14

User report: clicking Extract text again still jumped to To review. Cause: in the browser,
Streamlit 1.65's radio remembers the picked label text (e.g. `1 · To extract (22)`); after an
extraction the count changes, the old label matches no option, and the page fell back to its
default step (To review when anything is pending). The step now lives in session state
(`review_section`) and the radio key carries the three counts, so a count change redraws the
radio at the saved step while clicks on an unchanged radio work normally. (An unkeyed radio
was tried first; in the browser it needed two clicks to switch back, because its identity
includes the starting index.) Tests use `app.radio[0]`; a new test extracts one of two sources
and stays in step 1 (AppTest does not send labels back like the browser, so it cannot reproduce
the original cause). Browser check in a temporary fixture data folder (data/fixture/ui-check,
deleted afterwards): stays in step 1 with updated counts after extracting; five single-click
switches between the steps all worked; Approve still moves to Reviewed. Checks:
**369 passed, 9 deselected**; Ruff, format and pip check passed. Restarted the live app
(viewing only).

## Metadata auto-fill, layer 1 (T12/T14) — 2026-10-14

The user agreed to deterministic rules first, with the eight-organisation domain table.
`gridlens/documents/metadata.py` reads hints from the fetched document: HTML head tags
(citation_*, Dublin Core, Open Graph, JSON-LD, `<time>`) and the PDF info dictionary (title with
junk filtered, creation date marked "PDF file date"), plus a domain table (Electricity
Authority, Transpower, MBIE, EECA, Commerce Commission, FERC, NERC, EIA) and domain rules for
region (.nz → NZ, .gov/.mil → US) and type (paper sites/journal tag → paper, .govt.nz/.gov →
policy). Only empty fields are filled. On a first extraction the hints apply before the
snapshot hash; each filled field's origin is stored in `metadata_hints` (not hashed) and shown on
the Review form until the reviewer saves a different value. Pending versions get "Fill empty
fields from the page", which reads only the saved copy (new `read_pdf_info` reads the PDF info
without page text). `parse_pdf` is unchanged; `parse_pdf_document` returns segments and info.
Read-only live preview over the 8 pending documents (saved copies only, nothing written): 7 would
gain values, 1 (media.umbraco.io) none. Known limits: third-party files hosted on a regulator's
site get the host as publisher (e.g. the EPOC submission on mbie.govt.nz), marked "website
domain"; a PDF creation date is not always the publication date. Checks: **380 passed,
9 deselected**; Ruff, format and pip check passed. Not run: the user's own use of the button in
live; layer 2 (AI suggestions) not started.

## Sidebar layout and tagline (T05/T36) — 2026-10-18

The user sent a sketch for the sidebar and asked for the tagline "Find. Verify. Know.". The
built-in page menu is now hidden (`st.navigation(position="hidden")`) and the sidebar draws its
own: GridLens and the tagline at the top, a RESEARCH WORKFLOW label with numbered links
① Discover … ④ Ask & Gaps (`st.page_link`, current page highlighted), then CHATGPT ACCOUNT with
the Account and Model pickers visible and Refresh models, Reauthorize, Sign out and Add another
account folded into a "Manage account" expander (View ChatGPT usage stays visible), and the data
mode at the bottom (live: "● Live mode" / "Local workspace"; fixture keeps its yellow warning).
Page URLs, titles and button labels are unchanged. Files: app.py, gridlens/ui/common.py,
gridlens/ui/account.py. Checks: **380 passed, 9 deselected**; Ruff and format passed. Restarted
the 8501 live app and checked the new sidebar in the browser, including the ② Review link
switching pages and moving the highlight (viewing only; no search, extraction or sign-in).
Note: a restart clears the chosen model, so it has to be picked again after each restart.
